"""The graph state: the single object every node reads from and writes to.

Design rules:
- Each node returns only the keys it changes; LangGraph merges them in.
- Values stay plain JSON (dicts, lists, strings, numbers) so the checkpointer can
  persist them anywhere (memory today, SQLite/Postgres later) and the API can
  return them as-is. Pydantic is used at the LLM boundary, not inside the state.
- Two keys use *reducers* instead of plain overwrite:
    usage            -> token and cost deltas are summed across nodes
    critique_history -> each critique pass is appended, so we can see how scores
                        moved across revisions
"""

import operator
from typing import Annotated, Any, TypedDict


def add_usage(left: dict | None, right: dict | None) -> dict:
    """Reducer: sum token counts, call counts and cost from every LLM call."""
    left, right = left or {}, right or {}
    return {
        "input_tokens": left.get("input_tokens", 0) + right.get("input_tokens", 0),
        "output_tokens": left.get("output_tokens", 0) + right.get("output_tokens", 0),
        "llm_calls": left.get("llm_calls", 0) + right.get("llm_calls", 0),
        "cost_usd": round(left.get("cost_usd", 0.0) + right.get("cost_usd", 0.0), 6),
    }


class AgentState(TypedDict, total=False):
    # ---- input ----
    source_url: str | None
    source_text: str | None
    requested_platforms: list[str]
    auto_approve: bool                    # evals only: skip the human interrupt

    # ---- fetch_and_chunk ----
    title: str
    chunks: list[str]
    source_truncated: bool                # True if the article was cut to fit the context budget

    # ---- plan ----
    plan: dict[str, Any]                  # Plan.model_dump()

    # ---- write <-> critique loop ----
    posts: dict[str, str]                 # platform -> post text
    last_written: list[str]               # platforms written in the latest write pass
    critique: dict[str, dict[str, Any]]   # platform -> latest scores + feedback
    critique_history: Annotated[list[dict[str, Any]], operator.add]
    revisions: int                        # rewrite passes done after the first draft

    # ---- human_review + schedule ----
    review: dict[str, Any]
    scheduled: list[dict[str, Any]]

    # ---- bookkeeping ----
    status: str
    usage: Annotated[dict[str, Any], add_usage]
