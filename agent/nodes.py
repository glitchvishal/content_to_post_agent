"""The graph nodes.

Each node is a plain method: it receives the current state and returns a dict
with only the keys it changes. Dependencies (the LLM client and settings) are
injected through the constructor, so tests can pass a FakeLLM.

Flow:  fetch_and_chunk -> plan -> write -> critique --(fail & budget left)--> write
                                                    \\--(pass or budget used)--> human_review -> schedule
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END
from langgraph.types import interrupt

from agent import prompts
from agent.config import Settings
from agent.errors import ContentError
from agent.fetch import chunk_text, fetch_url, normalize_text
from agent.llm import LLMClient
from agent.platforms import PLATFORMS, SUPPORTED_PLATFORMS
from agent.review import validate_review
from agent.schemas import Critique, Draft, Plan
from agent.state import AgentState, add_usage
from agent.tools import make_schedule_tool


class AgentNodes:
    def __init__(self, llm: LLMClient, settings: Settings):
        self.llm = llm
        self.settings = settings
        self.schedule_tool = make_schedule_tool(settings.schedule_file)

    # ------------------------------------------------------------------ 1. fetch_and_chunk

    def fetch_and_chunk(self, state: AgentState) -> dict[str, Any]:
        """Get the source text (URL or raw text), clean it, split it into numbered chunks."""
        s = self.settings
        if state.get("source_url"):
            title, text = fetch_url(
                state["source_url"],
                timeout_s=s.fetch_timeout_s,
                max_attempts=s.fetch_max_attempts,
                allow_private=s.allow_private_urls,
            )
        else:
            title, text = "", normalize_text(state.get("source_text") or "")

        if len(text) < s.min_source_chars:
            raise ContentError(
                f"Only {len(text)} characters of readable text found; need at least {s.min_source_chars}. "
                "If the page needs JavaScript or a login, paste the article text instead."
            )

        # Keep chunks until the context budget is used. Long articles are cut, and we say so.
        chunks = chunk_text(text, s.chunk_max_chars)
        kept, used = [], 0
        for chunk in chunks:
            if kept and used + len(chunk) > s.max_source_chars:
                break
            kept.append(chunk)
            used += len(chunk)

        return {"title": title, "chunks": kept, "source_truncated": len(kept) < len(chunks), "status": "planning"}

    # ------------------------------------------------------------------ 2. plan

    def plan(self, state: AgentState) -> dict[str, Any]:
        """Extract key points (with the chunk ids that support them) and pick an angle + platforms."""
        requested = state.get("requested_platforms") or list(SUPPORTED_PLATFORMS)
        chunks = state["chunks"]
        plan, usage = self.llm.structured(
            Plan, prompts.PLAN_SYSTEM, prompts.plan_user(state.get("title", ""), chunks, requested), role="planner"
        )

        # Never trust the model blindly: keep only platforms the user allowed and chunk ids that exist.
        platforms = [p for p in dict.fromkeys(plan.platforms) if p in requested] or requested
        for kp in plan.key_points:
            kp.chunk_ids = [cid for cid in kp.chunk_ids if 1 <= cid <= len(chunks)]
        plan.platforms = platforms

        return {"plan": plan.model_dump(), "title": state.get("title") or plan.title, "status": "writing", "usage": usage}

    # ------------------------------------------------------------------ 3. write

    def write(self, state: AgentState) -> dict[str, Any]:
        """Write one post per platform. On a revision pass, rewrite only the posts that failed."""
        plan = state["plan"]
        critique = state.get("critique") or {}
        is_revision = bool(critique)
        posts = dict(state.get("posts") or {})
        evidence = self._evidence(state)

        targets = [p for p in plan["platforms"] if not is_revision or not critique[p]["passed"]]
        usage: dict = {}
        for platform in targets:
            spec = PLATFORMS[platform]
            user = prompts.write_user(
                spec,
                plan,
                evidence,
                previous_draft=posts.get(platform) if is_revision else None,
                feedback=critique.get(platform) if is_revision else None,
            )
            draft, call_usage = self.llm.structured(Draft, prompts.write_system(spec), user, role="writer")
            posts[platform] = draft.text.strip()
            usage = add_usage(usage, call_usage)

        return {
            "posts": posts,
            "last_written": targets,
            "revisions": state.get("revisions", 0) + (1 if is_revision else 0),
            "status": "critiquing",
            "usage": usage,
        }

    # ------------------------------------------------------------------ 4. critique

    def critique(self, state: AgentState) -> dict[str, Any]:
        """LLM-as-judge scores each new post, then deterministic guardrails tighten the scores."""
        plan = state["plan"]
        evidence = self._evidence(state)
        critique = dict(state.get("critique") or {})  # unchanged posts keep their previous scores
        history, usage = [], {}

        for platform in state["last_written"]:
            spec = PLATFORMS[platform]
            post = state["posts"][platform]
            judged, call_usage = self.llm.structured(
                Critique, prompts.CRITIQUE_SYSTEM, prompts.critique_user(spec, post, evidence, plan), role="judge"
            )
            result = apply_guardrails(judged, post, spec.max_chars, self.settings.pass_threshold)
            critique[platform] = result
            history.append({"revision": state.get("revisions", 0), "platform": platform, **result})
            usage = add_usage(usage, call_usage)

        return {"critique": critique, "critique_history": history, "usage": usage, "status": "reviewing"}

    def route_after_critique(self, state: AgentState) -> Literal["write", "human_review"]:
        """The loop's exit condition. It always terminates: revisions grows by 1 per pass and is capped."""
        any_failed = any(not c["passed"] for c in state["critique"].values())
        if any_failed and state.get("revisions", 0) < self.settings.max_revisions:
            return "write"
        return "human_review"

    # ------------------------------------------------------------------ 5. human_review

    def human_review(self, state: AgentState) -> dict[str, Any]:
        """Pause the graph and wait for a human: approve, edit or reject.

        `interrupt()` saves the state through the checkpointer and stops the run.
        When the run is resumed with Command(resume=decision), this node runs again
        from the top and `interrupt()` returns the decision. Everything before the
        interrupt call must therefore be safe to run twice (it is: it only reads state).
        """
        if state.get("auto_approve"):  # used by evals only
            return {"review": {"decision": "approve", "by": "auto"}, "status": "approved"}

        failing = [p for p, c in state["critique"].items() if not c["passed"]]
        decision = interrupt(
            {
                "type": "review_request",
                "posts": state["posts"],
                "critique": state["critique"],
                "revisions": state.get("revisions", 0),
                "warnings": [f"{PLATFORMS[p].name} post is below the quality bar after all revisions." for p in failing],
                "expected": {"decision": "approve | edit | reject", "posts": "{platform: text} for edit", "reason": "optional"},
            }
        )

        review = validate_review(decision, state["posts"])
        if review.decision == "reject":
            return {"review": review.model_dump(mode="json"), "status": "rejected"}
        posts = {**state["posts"], **(review.posts or {})}
        return {"review": review.model_dump(mode="json"), "posts": posts, "status": "approved"}

    @staticmethod
    def route_after_review(state: AgentState) -> Literal["schedule", "__end__"]:
        return "schedule" if state.get("status") == "approved" else END

    # ------------------------------------------------------------------ 6. schedule

    def schedule(self, state: AgentState, config: RunnableConfig) -> dict[str, Any]:
        """Call the (mock) schedule_post tool once per approved post."""
        review = state.get("review") or {}
        # Defense in depth: the graph only routes here after approval, but the side effect checks too.
        if review.get("decision") not in ("approve", "edit"):
            raise RuntimeError("Refusing to schedule posts without a human approval.")

        if review.get("schedule_at"):
            when = datetime.fromisoformat(review["schedule_at"]).astimezone(timezone.utc)
        else:
            when = datetime.now(timezone.utc) + timedelta(minutes=self.settings.schedule_delay_minutes)

        run_id = config["configurable"]["thread_id"]
        scheduled = [
            self.schedule_tool.invoke(
                {
                    "platform": platform,
                    "text": state["posts"][platform],
                    "scheduled_at_utc": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "run_id": run_id,
                    "source_url": state.get("source_url") or "",
                }
            )
            for platform in state["plan"]["platforms"]
        ]
        return {"scheduled": scheduled, "status": "completed"}

    # ------------------------------------------------------------------ helpers

    def _evidence(self, state: AgentState) -> list[tuple[int, str]]:
        """The chunks the plan's key points cite: what the writer may use and the judge checks against."""
        chunks = state["chunks"]
        ids = sorted({cid for kp in state["plan"]["key_points"] for cid in kp["chunk_ids"]})
        ids = ids or list(range(1, min(len(chunks), 2) + 1))  # fallback: the first chunks
        return [(cid, chunks[cid - 1]) for cid in ids]


def apply_guardrails(judged: Critique, post: str, max_chars: int, threshold: int) -> dict[str, Any]:
    """Combine the LLM judge's scores with checks code can do exactly.

    LLMs are bad at counting characters, so length is enforced here, not trusted to
    the judge. Any unsupported claim the judge lists also caps faithfulness below
    the pass mark, so a post with an invented fact can never pass.
    """
    scores = {"faithfulness": judged.faithfulness, "platform_fit": judged.platform_fit, "hook": judged.hook}
    notes = []
    if len(post) > max_chars:
        scores["platform_fit"] = min(scores["platform_fit"], 3)
        notes.append(f"The post is {len(post)} characters; the limit is {max_chars}. Cut at least {len(post) - max_chars}.")
    if judged.unsupported_claims:
        scores["faithfulness"] = min(scores["faithfulness"], threshold - 1)
        notes.append("Remove every claim the source does not support.")
    if not post.strip():
        scores = {key: 1 for key in scores}
        notes.append("The post is empty.")

    return {
        **scores,
        "unsupported_claims": judged.unsupported_claims,
        "feedback": " ".join([*notes, judged.feedback]).strip(),
        "chars": len(post),
        "passed": all(value >= threshold for value in scores.values()),
    }
