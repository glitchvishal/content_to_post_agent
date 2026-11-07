"""Offline evaluation of the agent.

Runs every article in evals/dataset.json through the full graph with
auto-approve (no human pause), then reports quality scores from the LLM judge,
how often the critique loop had to rewrite, latency and cost.

    python evals/run_evals.py                 # real model (needs OPENAI_API_KEY)
    python evals/run_evals.py --limit 3       # quick check
    python evals/run_evals.py --fake          # offline smoke test of the harness itself

Writes evals/results.md (human-readable) and evals/results.json (raw).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import statistics
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # allow `python evals/run_evals.py` from the repo root

from agent.config import get_settings  # noqa: E402
from agent.errors import AgentError  # noqa: E402
from agent.graph import build_graph, initial_state  # noqa: E402

METRICS = ("faithfulness", "platform_fit", "hook")


def _mean(values: list[float]) -> float:
    return round(statistics.mean(values), 2) if values else 0.0


def run_one(graph, article: dict) -> dict:
    config = {"configurable": {"thread_id": f"eval-{article['id']}"}}
    started = time.monotonic()
    try:
        graph.invoke(initial_state(text=article["text"], auto_approve=True), config)
        error = None
    except AgentError as exc:
        error = f"{exc.code}: {exc}"
    latency = time.monotonic() - started
    values = graph.get_state(config).values

    critique = values.get("critique") or {}
    first_pass = [h for h in values.get("critique_history", []) if h["revision"] == 0]
    # Deterministic check for content that must never appear (e.g. a prompt-injection payload).
    posts = values.get("posts", {})
    violations = [
        f"{platform}: '{phrase}'"
        for platform, text in posts.items()
        for phrase in article.get("must_not_contain", [])
        if phrase.lower() in text.lower()
    ]
    return {
        "id": article["id"],
        "title": article["title"],
        "tags": article.get("tags", []),
        "error": error,
        "latency_s": round(latency, 2),
        "revisions": values.get("revisions", 0),
        "cost_usd": (values.get("usage") or {}).get("cost_usd", 0.0),
        "tokens": (values.get("usage") or {}).get("input_tokens", 0) + (values.get("usage") or {}).get("output_tokens", 0),
        "final": {p: {m: c[m] for m in (*METRICS, "passed", "chars")} for p, c in critique.items()},
        "first_draft": {h["platform"]: {m: h[m] for m in (*METRICS, "passed")} for h in first_pass},
        "violations": violations,
        "posts": posts,
    }


def summarize(results: list[dict]) -> dict:
    ok = [r for r in results if not r["error"]]
    finals = [s for r in ok for s in r["final"].values()]
    firsts = [s for r in ok for s in r["first_draft"].values()]
    by_platform = {}
    for platform in sorted({p for r in ok for p in r["final"]}):
        rows = [r["final"][platform] for r in ok if platform in r["final"]]
        by_platform[platform] = {m: _mean([row[m] for row in rows]) for m in METRICS}
    return {
        "articles": len(results),
        "errors": len(results) - len(ok),
        "final_pass_rate": _mean([all(s["passed"] for s in r["final"].values()) for r in ok]),
        "first_draft_pass_rate": _mean([all(s["passed"] for s in r["first_draft"].values()) for r in ok]),
        "revision_rate": _mean([r["revisions"] > 0 for r in ok]),
        "avg_revisions": _mean([r["revisions"] for r in ok]),
        "first_draft_avg": {m: _mean([s[m] for s in firsts]) for m in METRICS},
        "final_avg": {m: _mean([s[m] for s in finals]) for m in METRICS},
        "by_platform": by_platform,
        "violations": sum(len(r["violations"]) for r in ok),
        "avg_latency_s": _mean([r["latency_s"] for r in ok]),
        "p95_latency_s": round(sorted(r["latency_s"] for r in ok)[max(0, int(len(ok) * 0.95) - 1)], 2) if ok else 0.0,
        "avg_cost_usd": round(statistics.mean([r["cost_usd"] for r in ok]), 5) if ok else 0.0,
        "total_cost_usd": round(sum(r["cost_usd"] for r in results), 5),
    }


def to_markdown(summary: dict, results: list[dict], settings, fake: bool) -> str:
    pct = lambda x: f"{x * 100:.0f}%"  # noqa: E731
    lines = [
        "# Eval results",
        "",
        f"- Run at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"- Writer/planner model: `{'fake' if fake else settings.openai_model}` · judge model: `{'fake' if fake else settings.judge_model}`",
        f"- Pass threshold: every score >= {settings.pass_threshold} · max revisions: {settings.max_revisions}",
        "",
    ]
    if fake:
        lines += [
            "> ⚠️ **Generated with the offline fake LLM.** These numbers only prove the eval harness works.",
            "> They say nothing about quality. Run `python evals/run_evals.py` with an OpenAI key for real results.",
            "",
        ]
    fd, fa = summary["first_draft_avg"], summary["final_avg"]
    lines += [
        "## Summary",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Articles (errors) | {summary['articles']} ({summary['errors']}) |",
        f"| Pass rate: first draft → final | {pct(summary['first_draft_pass_rate'])} → {pct(summary['final_pass_rate'])} |",
        f"| Revision rate (runs needing ≥1 rewrite) | {pct(summary['revision_rate'])} |",
        f"| Avg revisions per run | {summary['avg_revisions']} |",
        f"| Faithfulness: first draft → final | {fd['faithfulness']} → {fa['faithfulness']} |",
        f"| Platform fit: first draft → final | {fd['platform_fit']} → {fa['platform_fit']} |",
        f"| Hook: first draft → final | {fd['hook']} → {fa['hook']} |",
        f"| Must-not-contain violations (e.g. prompt injection) | {summary['violations']} |",
        f"| Avg / p95 latency | {summary['avg_latency_s']}s / {summary['p95_latency_s']}s |",
        f"| Avg cost per run / total | ${summary['avg_cost_usd']:.4f} / ${summary['total_cost_usd']:.4f} |",
        "",
        "## By platform (final scores)",
        "",
        "| Platform | Faithfulness | Platform fit | Hook |",
        "|---|---|---|---|",
        *[f"| {p} | {s['faithfulness']} | {s['platform_fit']} | {s['hook']} |" for p, s in summary["by_platform"].items()],
        "",
        "## Per article (final scores, averaged over platforms)",
        "",
        "| Article | Faithfulness | Fit | Hook | Revisions | Passed | Latency | Cost |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        if r["error"]:
            lines.append(f"| {r['id']} | — | — | — | — | error: {r['error'][:60]} | {r['latency_s']}s | — |")
            continue
        scores = list(r["final"].values())
        avg = {m: _mean([s[m] for s in scores]) for m in METRICS}
        passed = "✅" if all(s["passed"] for s in scores) else "❌"
        if r["violations"]:
            passed += " ⚠️ " + "; ".join(r["violations"])
        lines.append(
            f"| {r['id']} | {avg['faithfulness']} | {avg['platform_fit']} | {avg['hook']} | "
            f"{r['revisions']} | {passed} | {r['latency_s']}s | ${r['cost_usd']:.4f} |"
        )
    lines += [
        "",
        "## How to read this",
        "",
        "- Scores come from the LLM judge (1-10) plus code guardrails: a post over the character limit is capped at 3 for platform fit, and any unsupported claim caps faithfulness below the pass mark.",
        "- The judge is itself a model, so treat scores as a regression signal (did a prompt change make things better or worse?), not ground truth. Spot-check posts in `results.json` by hand.",
        "- `pricing-page-injection` contains an instruction hidden in the article. Any post containing one of its `must_not_contain` phrases is counted as a violation above.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the agent over evals/dataset.json and report scores.")
    parser.add_argument("--fake", action="store_true", help="Use the offline fake LLM (tests the harness only).")
    parser.add_argument("--limit", type=int, default=None, help="Only run the first N articles.")
    parser.add_argument("--out", default=str(ROOT / "evals" / "results.md"))
    args = parser.parse_args()

    articles = json.loads((ROOT / "evals" / "dataset.json").read_text())["articles"][: args.limit]
    settings = get_settings()
    # Auto-approved eval runs must never touch the real schedule file.
    scratch = Path(tempfile.mkdtemp(prefix="evals-"))
    settings = dataclasses.replace(settings, schedule_file=str(scratch / "scheduled.json"))
    if args.fake:
        settings = dataclasses.replace(settings, llm_provider="fake")
    graph = build_graph(settings=settings)

    results = []
    for i, article in enumerate(articles, 1):
        result = run_one(graph, article)
        status = result["error"] or f"revisions={result['revisions']} cost=${result['cost_usd']:.4f}"
        print(f"[{i}/{len(articles)}] {article['id']:<24} {result['latency_s']:>6.1f}s  {status}")
        results.append(result)

    summary = summarize(results)
    out = Path(args.out)
    out.write_text(to_markdown(summary, results, settings, args.fake))
    out.with_suffix(".json").write_text(json.dumps({"summary": summary, "results": results}, indent=2, ensure_ascii=False))
    print(f"\nFinal pass rate {summary['final_pass_rate'] * 100:.0f}% · revision rate {summary['revision_rate'] * 100:.0f}% · "
          f"avg cost ${summary['avg_cost_usd']:.4f} · total ${summary['total_cost_usd']:.4f}")
    print(f"Wrote {out} and {out.with_suffix('.json')}")
    return 0 if summary["errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
