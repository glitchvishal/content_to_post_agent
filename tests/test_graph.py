import json

import pytest
from langgraph.types import Command

from agent.errors import ContentError, ReviewError
from agent.graph import initial_state
from agent.nodes import AgentNodes, apply_guardrails
from agent.schemas import Critique

from .conftest import ARTICLE


def _cfg(run_id="run-1"):
    return {"configurable": {"thread_id": run_id}}


def _start(graph, run_id="run-1", **kwargs):
    graph.invoke(initial_state(text=ARTICLE, **kwargs), _cfg(run_id))
    return graph.get_state(_cfg(run_id))


def test_run_pauses_at_human_review_after_one_revision(graph, fake_llm):
    snapshot = _start(graph)
    values = snapshot.values

    assert snapshot.next == ("human_review",)  # paused by interrupt()
    assert set(values["posts"]) == {"linkedin", "x"}
    # FakeLLM writes a weak hook first, so the loop rewrites exactly once.
    assert values["revisions"] == 1
    assert all(c["passed"] for c in values["critique"].values())
    assert [h["revision"] for h in values["critique_history"]] == [0, 0, 1, 1]
    assert fake_llm.calls == ["Plan", "Draft", "Draft", "Critique", "Critique", "Draft", "Draft", "Critique", "Critique"]
    # Usage is summed across all 9 calls by the reducer.
    assert values["usage"]["llm_calls"] == 9 and values["usage"]["cost_usd"] > 0
    assert len(values["posts"]["x"]) <= 280


def test_approve_schedules_posts(graph, settings):
    _start(graph)
    graph.invoke(Command(resume={"decision": "approve"}), _cfg())
    values = graph.get_state(_cfg()).values

    assert values["status"] == "completed"
    saved = json.loads(open(settings.schedule_file).read())
    assert {e["platform"] for e in saved} == {"linkedin", "x"}
    assert all(e["scheduled_at_utc"].endswith("Z") and e["run_id"] == "run-1" for e in saved)


def test_edit_uses_human_text(graph, settings):
    _start(graph)
    graph.invoke(Command(resume={"decision": "edit", "posts": {"x": "  Human-written post.  "}}), _cfg())
    saved = {e["platform"]: e["text"] for e in json.loads(open(settings.schedule_file).read())}
    assert saved["x"] == "Human-written post."


def test_reject_never_schedules(graph, settings):
    _start(graph)
    graph.invoke(Command(resume={"decision": "reject", "reason": "off-brand"}), _cfg())
    values = graph.get_state(_cfg()).values
    assert values["status"] == "rejected"
    assert values["review"]["reason"] == "off-brand"
    assert not graph.get_state(_cfg()).next
    with pytest.raises(FileNotFoundError):
        open(settings.schedule_file)


def test_auto_approve_runs_to_completion(graph):
    graph.invoke(initial_state(text=ARTICLE, auto_approve=True), _cfg("auto"))
    assert graph.get_state(_cfg("auto")).values["status"] == "completed"


def test_platform_subset(graph):
    values = _start(graph, platforms=["linkedin"]).values
    assert list(values["posts"]) == ["linkedin"]


def test_too_short_input_fails_clearly(graph):
    with pytest.raises(ContentError, match="need at least"):
        graph.invoke(initial_state(text="Too short."), _cfg("short"))


def test_scheduling_is_idempotent(settings, fake_llm):
    tool = AgentNodes(fake_llm, settings).schedule_tool
    args = {"platform": "x", "text": "hi", "scheduled_at_utc": "2030-01-01T00:00:00Z", "run_id": "r"}
    first, second = tool.invoke(args), tool.invoke(args)
    assert first["id"] == second["id"]
    assert len(json.loads(open(settings.schedule_file).read())) == 1


# ---------------------------------------------------------------- routing and guardrails


def _nodes(settings, fake_llm):
    return AgentNodes(fake_llm, settings)


def test_router_loops_until_pass_or_budget(settings, fake_llm):
    nodes = _nodes(settings, fake_llm)
    failing = {"critique": {"x": {"passed": False}}}
    passing = {"critique": {"x": {"passed": True}}}
    assert nodes.route_after_critique({**failing, "revisions": 0}) == "write"
    assert nodes.route_after_critique({**failing, "revisions": 1}) == "write"
    assert nodes.route_after_critique({**failing, "revisions": 2}) == "human_review"  # budget used
    assert nodes.route_after_critique({**passing, "revisions": 0}) == "human_review"


def test_guardrails_enforce_length_and_faithfulness():
    judged = Critique(faithfulness=9, platform_fit=9, hook=9, unsupported_claims=[], feedback="Great.")
    assert apply_guardrails(judged, "short post", 280, 7)["passed"]

    too_long = apply_guardrails(judged, "x" * 300, 280, 7)
    assert too_long["platform_fit"] == 3 and not too_long["passed"]
    assert "limit is 280" in too_long["feedback"]

    invented = Critique(faithfulness=9, platform_fit=9, hook=9, unsupported_claims=["Revenue tripled"], feedback="ok")
    result = apply_guardrails(invented, "short post", 280, 7)
    assert result["faithfulness"] == 6 and not result["passed"]


def test_invalid_review_is_rejected_before_resume(graph):
    from agent.review import validate_review

    posts = _start(graph).values["posts"]
    with pytest.raises(ReviewError, match="limit is 280"):
        validate_review({"decision": "edit", "posts": {"x": "a" * 281}}, posts)
    with pytest.raises(ReviewError, match="needs `posts`"):
        validate_review({"decision": "edit"}, posts)
    with pytest.raises(ReviewError):
        validate_review({"decision": "maybe"}, posts)
    with pytest.raises(ReviewError, match="timezone"):
        validate_review({"decision": "approve", "schedule_at": "2030-01-01T09:00:00"}, posts)
