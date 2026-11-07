"""A deterministic, offline stand-in for the LLM.

NOT a model and NOT used to judge quality. It exists so that:
- the test suite and CI run with no API key and no network,
- you can demo the graph mechanics (loop, interrupt, resume, scheduling) offline:
  `LLM_PROVIDER=fake` or `python -m agent run --fake ...`.

It reads the same tagged prompts the real model gets (see prompts.py) and
returns schema-valid output. It deliberately writes a weak hook on the first
draft so the critique -> rewrite loop runs exactly once.
"""

from __future__ import annotations

import re

from agent.config import Settings
from agent.llm import Role, make_usage
from agent.schemas import Critique, Draft, KeyPoint, Plan

_CHUNK = re.compile(r'<chunk id="(\d+)">\s*(.*?)\s*</chunk>', re.S)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_WEAK_OPENER = "in this article"


def _tag(text: str, name: str) -> str:
    match = re.search(rf"<{name}>\s*(.*?)\s*</{name}>", text, re.S)
    return match.group(1) if match else ""


def _shorten(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:") + "…"


class FakeLLM:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings(llm_provider="fake")
        self.calls: list[str] = []  # schema names, in call order (handy in tests)

    def structured(self, schema, system: str, user: str, *, role: Role):
        self.calls.append(schema.__name__)
        if schema is Plan:
            result = self._plan(user)
        elif schema is Draft:
            result = self._draft(user)
        elif schema is Critique:
            result = self._critique(user)
        else:
            raise TypeError(f"FakeLLM does not know schema {schema.__name__}")
        # Rough token estimate (~4 chars per token) so cost tracking has numbers to show.
        usage = make_usage(
            self.settings.openai_model,
            (len(system) + len(user)) // 4,
            len(result.model_dump_json()) // 4,
            self.settings,
        )
        return result, usage

    # ---- one method per schema ----

    def _plan(self, user: str) -> Plan:
        chunks = [(int(cid), text) for cid, text in _CHUNK.findall(user)]
        allowed = [p.strip() for p in _tag(user, "allowed_platforms").split(",") if p.strip()]
        sentences = [(cid, s.strip()) for cid, text in chunks for s in _SENTENCE_END.split(text) if len(s.strip()) > 30]
        # First good sentence of each chunk, topped up from the rest, max 4 points.
        picked, seen_chunks = [], set()
        for cid, sentence in sentences:
            if cid not in seen_chunks:
                picked.append((cid, sentence))
                seen_chunks.add(cid)
        for item in sentences:
            if len(picked) >= 4:
                break
            if item not in picked:
                picked.append(item)
        picked = picked[:4] or [(1, chunks[0][1][:200])]

        title = _tag(user, "title")
        if title in ("", "unknown"):
            title = _shorten(picked[0][1], 80)
        return Plan(
            title=title,
            key_points=[KeyPoint(point=_shorten(s, 200), chunk_ids=[cid]) for cid, s in picked],
            angle=f"The practical lessons in '{title}'",
            audience="busy professionals",
            platforms=allowed or ["linkedin", "x"],
        )

    def _draft(self, user: str) -> Draft:
        platform = _tag(user, "platform")
        title = _tag(user, "title")
        points = [line[2:].strip() for line in _tag(user, "key_points").splitlines() if line.startswith("- ")]
        is_revision = bool(_tag(user, "feedback"))

        if platform == "x":
            text = points[0] if is_revision else f"In this article: {points[0]}"
            return Draft(text=_shorten(text, 270))

        hook = points[0] if is_revision else f"In this article, we look at {title}."
        bullets = "\n".join(f"• {p}" for p in (points[1:4] if is_revision else points[:3]))
        return Draft(text=_shorten(f"{hook}\n\n{bullets}\n\nWhich of these would you try first?", 1250))

    def _critique(self, user: str) -> Critique:
        post = _tag(user, "post")
        weak = post.lower().startswith(_WEAK_OPENER)
        return Critique(
            faithfulness=9,
            platform_fit=8,
            hook=5 if weak else 8,
            unsupported_claims=[],
            feedback=(
                "The opener is generic. Lead with the most concrete point instead of describing the article."
                if weak
                else "Strong, specific opener and faithful to the source. Keep it."
            ),
        )
