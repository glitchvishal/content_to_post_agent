"""Pydantic models for structured LLM output.

The LLM never returns free text that we then regex apart. Every call is bound
to one of these schemas, so the output is validated before it enters the graph
state. If validation fails, the call is retried (see llm.py).
"""

from typing import Literal

from pydantic import BaseModel, Field

PlatformName = Literal["linkedin", "x"]


class KeyPoint(BaseModel):
    point: str = Field(description="One specific, self-contained insight from the source, in your own words.")
    chunk_ids: list[int] = Field(description="IDs of the source chunks that support this point.")


class Plan(BaseModel):
    """Output of the `plan` node."""

    title: str = Field(description="Short title of the article (use the given title if there is one).")
    key_points: list[KeyPoint] = Field(min_length=1, max_length=8, description="3-6 key points, most important first.")
    angle: str = Field(description="The single framing that makes the posts worth reading, in one sentence.")
    audience: str = Field(description="Who the posts are for, in a few words.")
    platforms: list[PlatformName] = Field(description="Target platforms, chosen only from the allowed list.")


class Draft(BaseModel):
    """Output of the `write` node (one per platform)."""

    text: str = Field(description="The complete post text, ready to publish. Plain text only.")


class Critique(BaseModel):
    """Output of the `critique` node (LLM-as-judge, one per platform)."""

    faithfulness: int = Field(ge=1, le=10, description="Are all claims supported by the evidence? 1-10.")
    platform_fit: int = Field(ge=1, le=10, description="Length, tone and format fit for the platform. 1-10.")
    hook: int = Field(ge=1, le=10, description="Would the first line stop the target reader scrolling? 1-10.")
    unsupported_claims: list[str] = Field(description="Every claim in the post that the evidence does not support.")
    feedback: str = Field(description="1-3 concrete, actionable sentences for the writer.")
