"""The human review contract: what a reviewer can send back, and how it is validated.

Validation happens *before* the graph is resumed (in the API and CLI), so a bad
request gets a clear 422 / prompt instead of breaking the run. The node
validates again as a safety net.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from agent.errors import ReviewError
from agent.platforms import PLATFORMS


class ReviewDecision(BaseModel):
    decision: Literal["approve", "edit", "reject"]
    posts: dict[str, str] | None = Field(default=None, description="Edited text per platform (only for 'edit').")
    reason: str | None = Field(default=None, description="Optional note, e.g. why it was rejected.")
    schedule_at: datetime | None = Field(default=None, description="When to publish (timezone required). Default: now + delay.")


def validate_review(payload: dict | ReviewDecision, current_posts: dict[str, str]) -> ReviewDecision:
    try:
        review = payload if isinstance(payload, ReviewDecision) else ReviewDecision.model_validate(payload)
    except ValidationError as exc:
        raise ReviewError(f"Invalid review: {exc.errors()[0]['msg']}") from exc

    if review.decision == "edit":
        if not review.posts:
            raise ReviewError("An 'edit' decision needs `posts`: the edited text for at least one platform.")
        cleaned = {}
        for platform, text in review.posts.items():
            if platform not in current_posts:
                raise ReviewError(f"Unknown platform '{platform}'. Editable: {', '.join(current_posts)}.")
            text = text.strip()
            spec = PLATFORMS[platform]
            if not text:
                raise ReviewError(f"The edited {spec.name} post is empty.")
            if len(text) > spec.max_chars:
                raise ReviewError(f"The edited {spec.name} post is {len(text)} characters; the limit is {spec.max_chars}.")
            cleaned[platform] = text
        review.posts = cleaned
    else:
        review.posts = None  # posts are only meaningful for edits

    if review.schedule_at is not None:
        if review.schedule_at.tzinfo is None:
            raise ReviewError("schedule_at needs a timezone, e.g. 2026-11-08T09:00:00+05:30.")
        if review.schedule_at <= datetime.now(timezone.utc):
            raise ReviewError("schedule_at must be in the future.")
    return review
