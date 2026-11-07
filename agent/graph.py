"""Wire the nodes into a LangGraph StateGraph and compile it with a checkpointer."""

from __future__ import annotations

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from agent.config import Settings, get_settings
from agent.llm import LLMClient, get_llm
from agent.nodes import AgentNodes
from agent.state import AgentState


def build_graph(
    settings: Settings | None = None,
    llm: LLMClient | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
):
    settings = settings or get_settings()
    nodes = AgentNodes(llm or get_llm(settings), settings)

    builder = StateGraph(AgentState)
    builder.add_node("fetch_and_chunk", nodes.fetch_and_chunk)
    builder.add_node("plan", nodes.plan)
    builder.add_node("write", nodes.write)
    builder.add_node("critique", nodes.critique)
    builder.add_node("human_review", nodes.human_review)
    builder.add_node("schedule", nodes.schedule)

    builder.add_edge(START, "fetch_and_chunk")
    builder.add_edge("fetch_and_chunk", "plan")
    builder.add_edge("plan", "write")
    builder.add_edge("write", "critique")
    # The quality loop: back to `write` with feedback, or on to the human.
    builder.add_conditional_edges("critique", nodes.route_after_critique, {"write": "write", "human_review": "human_review"})
    # Only an approved (or edited) run reaches the side effect.
    builder.add_conditional_edges("human_review", nodes.route_after_review, {"schedule": "schedule", END: END})
    builder.add_edge("schedule", END)

    # The checkpointer saves state after every node. That is what lets interrupt()
    # pause the run at human_review and resume it later, keyed by thread_id (= run id).
    return builder.compile(checkpointer=checkpointer or MemorySaver())


def initial_state(
    url: str | None = None,
    text: str | None = None,
    platforms: list[str] | None = None,
    auto_approve: bool = False,
) -> dict:
    if bool(url) == bool(text):
        raise ValueError("Provide exactly one of `url` or `text`.")
    return {
        "source_url": url,
        "source_text": text,
        "requested_platforms": platforms or [],
        "auto_approve": auto_approve,
        "revisions": 0,
        "status": "fetching",
    }


def summarize_update(node: str, update: dict) -> dict:
    """A small, human-readable summary of what a node just did (for progress events and the CLI)."""
    update = update or {}
    if node == "fetch_and_chunk":
        return {"title": update.get("title"), "chunks": len(update.get("chunks", [])), "truncated": update.get("source_truncated")}
    if node == "plan":
        plan = update.get("plan", {})
        return {"angle": plan.get("angle"), "platforms": plan.get("platforms"), "key_points": len(plan.get("key_points", []))}
    if node == "write":
        return {"written": update.get("last_written"), "revision": update.get("revisions")}
    if node == "critique":
        return {
            "scores": {
                h["platform"]: {k: h[k] for k in ("faithfulness", "platform_fit", "hook", "passed")}
                for h in update.get("critique_history", [])
            }
        }
    if node == "human_review":
        return {"decision": (update.get("review") or {}).get("decision")}
    if node == "schedule":
        return {"scheduled": [{"platform": e["platform"], "at": e["scheduled_at_utc"]} for e in update.get("scheduled", [])]}
    return {}
