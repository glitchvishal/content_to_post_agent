"""Run manager: drives graph runs in background threads and records progress events.

The checkpointer is the source of truth for the agent state (posts, scores, ...).
This class only keeps per-run metadata (status, error, timestamps) and an
append-only event log that the SSE endpoint replays to any number of clients.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from langgraph.types import Command

from agent.errors import AgentError, ReviewError
from agent.graph import summarize_update
from agent.review import ReviewDecision, validate_review

log = logging.getLogger("content_to_post.api")

# A stream of events ends when the run reaches one of these. `awaiting_review`
# ends the current stream; resuming the run starts producing events again.
STREAM_END_STATUSES = {"awaiting_review", "completed", "rejected", "failed"}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class RunConflict(Exception):
    """The run is not in a state that allows this action (e.g. reviewing twice)."""


@dataclass
class RunRecord:
    run_id: str
    source: dict[str, Any]
    status: str = "queued"
    error: dict[str, Any] | None = None
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    events: list[dict[str, Any]] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


class RunManager:
    def __init__(self, graph):
        self.graph = graph
        self.runs: dict[str, RunRecord] = {}

    def _config(self, run_id: str) -> dict:
        return {"configurable": {"thread_id": run_id}}

    def _emit(self, record: RunRecord, event: str, data: dict[str, Any]) -> None:
        record.events.append({"event": event, "data": {"run_id": record.run_id, "ts": _now(), **data}})
        record.updated_at = _now()

    # ------------------------------------------------------------------ lifecycle

    def create(self, source: dict[str, Any]) -> RunRecord:
        record = RunRecord(run_id=str(uuid.uuid4()), source=source)
        self.runs[record.run_id] = record
        self._emit(record, "status", {"status": "queued"})
        return record

    def start(self, run_id: str, graph_input: dict) -> None:
        """Run from the beginning until the human review pause (or the end). Blocking: call in a thread."""
        self._drive(self.runs[run_id], graph_input)

    def resume(self, run_id: str, payload: dict) -> ReviewDecision:
        """Validate a review and claim the run. Raises RunConflict / ReviewError before anything changes."""
        record = self.runs[run_id]
        with record.lock:  # two reviewers clicking at once: only one wins
            if record.status != "awaiting_review":
                raise RunConflict(f"Run is '{record.status}', not 'awaiting_review'.")
            posts = self.graph.get_state(self._config(run_id)).values.get("posts", {})
            review = validate_review(payload, posts)
            record.status = "running"
        return review

    def continue_after_review(self, run_id: str, review: ReviewDecision) -> None:
        """Resume the paused graph with the reviewer's decision. Blocking: call in a thread."""
        record = self.runs[run_id]
        self._emit(record, "review", {"decision": review.decision})
        self._drive(record, Command(resume=review.model_dump(mode="json")))

    def _drive(self, record: RunRecord, graph_input: Any) -> None:
        config = self._config(record.run_id)
        record.status = "running"
        self._emit(record, "status", {"status": "running"})
        started = time.monotonic()
        try:
            for chunk in self.graph.stream(graph_input, config, stream_mode="updates"):
                for node, update in chunk.items():
                    if node == "__interrupt__":
                        continue
                    self._emit(record, "node", {
                        "node": node,
                        "elapsed_s": round(time.monotonic() - started, 2),
                        **summarize_update(node, update),
                    })

            snapshot = self.graph.get_state(config)
            if snapshot.next:  # paused by interrupt() inside human_review
                status = "awaiting_review"
                self._emit(record, "review_required", {
                    "posts": snapshot.values.get("posts"),
                    "critique": snapshot.values.get("critique"),
                })
            else:
                status = snapshot.values.get("status", "completed")
            record.error = None
        except AgentError as exc:
            status = "failed"
            record.error = {"type": exc.code, "message": str(exc), "node": self._failed_node(config)}
        except Exception as exc:  # unexpected bug: log it, never leak a stack trace to clients
            log.exception("Run %s crashed", record.run_id)
            status = "failed"
            record.error = {"type": "internal_error", "message": f"{type(exc).__name__}: {exc}", "node": self._failed_node(config)}

        # Emit the final event *before* flipping the status, so SSE readers never miss it.
        self._emit(record, "status", {"status": status, "error": record.error})
        record.status = status

    def _failed_node(self, config: dict) -> str | None:
        try:
            nxt = self.graph.get_state(config).next
            return nxt[0] if nxt else None
        except Exception:
            return None

    # ------------------------------------------------------------------ read

    def view(self, run_id: str) -> dict[str, Any]:
        record = self.runs[run_id]
        values = self.graph.get_state(self._config(run_id)).values or {}
        plan = values.get("plan") or {}
        return {
            "run_id": run_id,
            "status": record.status,
            "error": record.error,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
            "source": record.source,
            "title": values.get("title"),
            "source_truncated": values.get("source_truncated"),
            "plan": {k: plan.get(k) for k in ("angle", "audience", "platforms", "key_points")} if plan else None,
            "posts": values.get("posts"),
            "critique": values.get("critique"),
            "revisions": values.get("revisions", 0),
            "review": values.get("review"),
            "scheduled": values.get("scheduled"),
            "usage": values.get("usage") or {"input_tokens": 0, "output_tokens": 0, "llm_calls": 0, "cost_usd": 0.0},
        }


__all__ = ["RunManager", "RunConflict", "ReviewError", "STREAM_END_STATUSES"]
