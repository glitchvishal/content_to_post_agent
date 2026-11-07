"""FastAPI app.

    POST /runs                 start a run (returns immediately with a run_id)
    GET  /runs/{id}            status, posts, scores, usage
    GET  /runs/{id}/events     live progress as Server-Sent Events
    POST /runs/{id}/review     approve / edit / reject (resumes the paused graph)
    GET  /health

Run locally:  uvicorn api.main:app --reload
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, HttpUrl, model_validator

from agent.config import Settings, get_settings
from agent.errors import ReviewError
from agent.graph import build_graph, initial_state
from agent.review import ReviewDecision
from api.runs import STREAM_END_STATUSES, RunConflict, RunManager


class RunRequest(BaseModel):
    url: HttpUrl | None = None
    text: str | None = Field(default=None, max_length=100_000)
    platforms: list[Literal["linkedin", "x"]] | None = None
    auto_approve: bool = Field(default=False, description="Skip human review. Meant for testing and evals.")

    @model_validator(mode="after")
    def exactly_one_source(self) -> "RunRequest":
        if bool(self.url) == bool(self.text):
            raise ValueError("Provide exactly one of `url` or `text`.")
        return self


def allowed_origins() -> list[str]:
    """Browser origins allowed to call the API (the web UI). Comma-separated ALLOWED_ORIGINS env var."""
    raw = os.getenv("ALLOWED_ORIGINS", "http://localhost:3001,http://localhost:3000")
    return [origin.strip().rstrip("/") for origin in raw.split(",") if origin.strip()]


def create_app(settings: Settings | None = None, graph=None) -> FastAPI:
    settings = settings or get_settings()
    manager = RunManager(graph or build_graph(settings=settings))
    background: set[asyncio.Task] = set()  # keep references so tasks are not garbage-collected

    app = FastAPI(
        title="Content-to-Post Agent",
        version="0.1.0",
        description="Turn an article into LinkedIn and X posts with a LangGraph agent, a quality loop and human review.",
    )
    app.state.manager = manager
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins(),
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    def _record(run_id: str):
        record = manager.runs.get(run_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Run not found.")
        return record

    def _in_background(func, *args) -> None:
        task = asyncio.create_task(asyncio.to_thread(func, *args))
        background.add(task)
        task.add_done_callback(background.discard)

    @app.get("/health")
    def health():
        model = "fake" if settings.llm_provider == "fake" else settings.openai_model
        return {"status": "ok", "llm_provider": settings.llm_provider, "model": model}

    @app.post("/runs", status_code=202)
    async def create_run(body: RunRequest):
        url = str(body.url) if body.url else None
        record = manager.create({"url": url, "text_chars": len(body.text or ""), "platforms": body.platforms})
        _in_background(manager.start, record.run_id, initial_state(url, body.text, body.platforms, body.auto_approve))
        rid = record.run_id
        return {
            "run_id": rid,
            "status": record.status,
            "links": {"self": f"/runs/{rid}", "events": f"/runs/{rid}/events", "review": f"/runs/{rid}/review"},
        }

    @app.get("/runs/{run_id}")
    def get_run(run_id: str):
        _record(run_id)
        return manager.view(run_id)

    @app.post("/runs/{run_id}/review")
    async def review_run(run_id: str, body: ReviewDecision):
        _record(run_id)
        try:
            review = manager.resume(run_id, body.model_dump())
        except RunConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ReviewError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        # Scheduling is fast (no LLM calls), so wait for it and return the final state.
        await asyncio.to_thread(manager.continue_after_review, run_id, review)
        return manager.view(run_id)

    @app.get("/runs/{run_id}/events")
    async def run_events(run_id: str, request: Request):
        """Server-Sent Events. Replays past events, then streams new ones until the run
        completes, fails, is rejected, or pauses for review. Supports Last-Event-ID."""
        record = _record(run_id)
        last_id = request.headers.get("last-event-id")
        start = int(last_id) + 1 if last_id and last_id.isdigit() else 0

        async def stream():
            index, idle = start, 0.0
            yield "retry: 2000\n\n"
            while True:
                while index < len(record.events):
                    event = record.events[index]
                    yield f"id: {index}\nevent: {event['event']}\ndata: {json.dumps(event['data'])}\n\n"
                    index, idle = index + 1, 0.0
                if record.status in STREAM_END_STATUSES and index >= len(record.events):
                    break
                if await request.is_disconnected():
                    break
                await asyncio.sleep(0.2)
                idle += 0.2
                if idle >= 15:  # heartbeat keeps proxies from closing the connection
                    yield ": keep-alive\n\n"
                    idle = 0.0

        headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
        return StreamingResponse(stream(), media_type="text/event-stream", headers=headers)

    return app


app = create_app()
