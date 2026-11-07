"""Typed errors.

Expected failures (bad URL, page too short, LLM unavailable, invalid review)
raise an `AgentError` subclass with a message a user can act on. The API and
CLI turn these into a clear `failed` state instead of a stack trace.
"""


class AgentError(Exception):
    code = "agent_error"


class FetchError(AgentError):
    """The URL could not be fetched or is not an article we can read."""

    code = "fetch_error"


class ContentError(AgentError):
    """The source was fetched but has too little usable text."""

    code = "content_error"


class LLMError(AgentError):
    """The model call failed after retries, or returned unusable output."""

    code = "llm_error"


class ReviewError(AgentError, ValueError):
    """A human review decision was malformed (e.g. an edited post is too long)."""

    code = "invalid_review"
