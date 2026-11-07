"""Command line interface.

    python -m agent run --url https://example.com/article
    python -m agent run --file article.txt --platforms linkedin
    python -m agent run --text "..." --auto-approve
    python -m agent run --file article.txt --fake        # offline demo, no API key
    python -m agent graph                                # print the graph as Mermaid
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
import time
import uuid

from langgraph.types import Command

from agent.config import get_settings
from agent.errors import AgentError, ReviewError
from agent.graph import build_graph, initial_state, summarize_update
from agent.platforms import PLATFORMS, SUPPORTED_PLATFORMS
from agent.review import validate_review


def _print_progress(node: str, update: dict, started: float) -> None:
    summary = summarize_update(node, update)
    if node == "critique":
        parts = [
            f"{p}: F{s['faithfulness']} P{s['platform_fit']} H{s['hook']} {'pass' if s['passed'] else 'FAIL'}"
            for p, s in summary["scores"].items()
        ]
        detail = " | ".join(parts)
    else:
        detail = ", ".join(f"{k}={v}" for k, v in summary.items() if v not in (None, [], {}))
    print(f"  ✓ {node:<16} {time.monotonic() - started:5.1f}s  {detail}")


def _show_posts(values: dict) -> None:
    for platform, text in values["posts"].items():
        c = values["critique"][platform]
        spec = PLATFORMS[platform]
        print(f"\n── {spec.name}  ({c['chars']}/{spec.max_chars} chars)  "
              f"faithfulness {c['faithfulness']} · fit {c['platform_fit']} · hook {c['hook']}"
              f"{'' if c['passed'] else '  ⚠ below quality bar'}")
        print(text)
        print(f"   judge: {c['feedback']}")


def _read_multiline(prompt: str) -> str:
    print(prompt + " (finish with a line containing only '.')")
    lines = []
    for line in sys.stdin:
        if line.rstrip("\n") == ".":
            break
        lines.append(line.rstrip("\n"))
    return "\n".join(lines)


def _ask_review(values: dict) -> dict:
    """Prompt until the reviewer gives a valid decision."""
    while True:
        choice = input("\n[a]pprove / [e]dit / [r]eject? ").strip().lower()[:1]
        if choice == "a":
            payload = {"decision": "approve"}
        elif choice == "r":
            payload = {"decision": "reject", "reason": input("Reason (optional): ").strip() or None}
        elif choice == "e":
            edits = {}
            for platform in values["posts"]:
                if input(f"Edit the {PLATFORMS[platform].name} post? [y/N] ").strip().lower() == "y":
                    edits[platform] = _read_multiline(f"New {PLATFORMS[platform].name} text")
            payload = {"decision": "edit", "posts": edits}
        else:
            continue
        try:
            validate_review(payload, values["posts"])
            return payload
        except ReviewError as exc:
            print(f"  ✗ {exc}")


def cmd_run(args: argparse.Namespace) -> int:
    settings = get_settings()
    if args.fake:
        settings = dataclasses.replace(settings, llm_provider="fake")
    text = open(args.file, encoding="utf-8").read() if args.file else args.text
    platforms = [p.strip() for p in args.platforms.split(",")] if args.platforms else None
    if platforms and any(p not in SUPPORTED_PLATFORMS for p in platforms):
        print(f"Unknown platform. Choose from: {', '.join(SUPPORTED_PLATFORMS)}", file=sys.stderr)
        return 2

    graph = build_graph(settings=settings)
    run_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": run_id}}
    graph_input: object = initial_state(url=args.url, text=text, platforms=platforms, auto_approve=args.auto_approve)

    model = "fake (offline demo)" if settings.llm_provider == "fake" else settings.openai_model
    print(f"Run {run_id}  ·  model: {model}")
    started = time.monotonic()
    try:
        while True:
            for chunk in graph.stream(graph_input, config, stream_mode="updates"):
                for node, update in chunk.items():
                    if node != "__interrupt__":
                        _print_progress(node, update, started)

            snapshot = graph.get_state(config)
            if not snapshot.next:  # finished
                break
            # Paused at human_review: show the posts and resume with the decision.
            _show_posts(snapshot.values)
            graph_input = Command(resume=_ask_review(snapshot.values))
    except AgentError as exc:
        print(f"\n✗ Run failed ({exc.code}): {exc}", file=sys.stderr)
        return 1

    values = graph.get_state(config).values
    if args.auto_approve:
        _show_posts(values)
    usage = values.get("usage", {})
    print(f"\nStatus: {values.get('status')}  ·  revisions: {values.get('revisions', 0)}  ·  "
          f"LLM calls: {usage.get('llm_calls', 0)}  ·  tokens: {usage.get('input_tokens', 0)} in / "
          f"{usage.get('output_tokens', 0)} out  ·  cost: ${usage.get('cost_usd', 0):.4f}  ·  "
          f"{time.monotonic() - started:.1f}s")
    for entry in values.get("scheduled") or []:
        print(f"  scheduled {entry['platform']} for {entry['scheduled_at_utc']}  →  {settings.schedule_file}")
    return 0


def cmd_graph(_: argparse.Namespace) -> int:
    from agent.config import Settings

    print(build_graph(settings=Settings(llm_provider="fake")).get_graph().draw_mermaid())
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m agent", description="Turn an article into reviewed social posts.")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Run the agent on a URL, text or file.")
    source = run.add_mutually_exclusive_group(required=True)
    source.add_argument("--url", help="Article URL to fetch.")
    source.add_argument("--text", help="Raw article text.")
    source.add_argument("--file", help="Path to a .txt/.md file with the article text.")
    run.add_argument("--platforms", help="Comma-separated subset of: linkedin,x (default: both).")
    run.add_argument("--auto-approve", action="store_true", help="Skip human review (testing only).")
    run.add_argument("--fake", action="store_true", help="Use the offline fake LLM (no API key needed).")
    run.set_defaults(func=cmd_run)

    sub.add_parser("graph", help="Print the graph as a Mermaid diagram.").set_defaults(func=cmd_graph)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
