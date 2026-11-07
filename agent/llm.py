"""LLM access: one small interface, retries, token usage and cost.

Every node talks to the model through `LLMClient.structured(...)`, which
returns a validated Pydantic object plus a usage record. Keeping this behind
one interface means:
- retries, timeouts and cost tracking live in one place, and
- tests and offline demos can swap in `FakeLLM` (fake_llm.py) with no API key.
"""

from __future__ import annotations

from typing import Literal, Protocol, TypeVar

import openai
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from agent.config import Settings
from agent.errors import LLMError

T = TypeVar("T", bound=BaseModel)
Role = Literal["planner", "writer", "judge"]

# USD per 1M tokens (input, output). Check https://openai.com/api/pricing before
# quoting numbers; override with PRICE_INPUT_PER_1M / PRICE_OUTPUT_PER_1M.
PRICES: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-nano": (0.10, 0.40),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
}

# Writer gets some creativity; planner and judge should be as deterministic as possible.
TEMPERATURE: dict[Role, float] = {"planner": 0.0, "writer": 0.7, "judge": 0.0}


class StructuredOutputError(Exception):
    """The model answered, but not in the requested schema. Retried like a transient error."""


_RETRYABLE = (
    openai.APIConnectionError,  # includes timeouts
    openai.RateLimitError,
    openai.InternalServerError,
    StructuredOutputError,
)


def estimate_cost(model: str, input_tokens: int, output_tokens: int, settings: Settings) -> float:
    if settings.price_input_per_1m is not None and settings.price_output_per_1m is not None:
        price_in, price_out = settings.price_input_per_1m, settings.price_output_per_1m
    else:
        # Match "gpt-4o-mini-2024-07-18" to "gpt-4o-mini"; longest prefix wins.
        matches = [name for name in PRICES if model.startswith(name)]
        price_in, price_out = PRICES[max(matches, key=len)] if matches else (0.0, 0.0)
    return (input_tokens * price_in + output_tokens * price_out) / 1_000_000


def make_usage(model: str, input_tokens: int, output_tokens: int, settings: Settings) -> dict:
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "llm_calls": 1,
        "cost_usd": round(estimate_cost(model, input_tokens, output_tokens, settings), 6),
    }


class LLMClient(Protocol):
    def structured(self, schema: type[T], system: str, user: str, *, role: Role) -> tuple[T, dict]:
        """Call the model and return (validated output, usage dict)."""
        ...


class OpenAIClient:
    """Real client: LangChain's ChatOpenAI with structured output, our own retry policy."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._runnables: dict[tuple[Role, str], object] = {}

    def model_for(self, role: Role) -> str:
        return self.settings.judge_model if role == "judge" else self.settings.openai_model

    def _runnable(self, schema: type[BaseModel], role: Role):
        key = (role, schema.__name__)
        if key not in self._runnables:
            chat = ChatOpenAI(
                model=self.model_for(role),
                temperature=TEMPERATURE[role],
                timeout=self.settings.llm_timeout_s,
                max_retries=0,  # retries are handled below so the policy is explicit and testable
                api_key=self.settings.openai_api_key,
            )
            # include_raw=True gives us the raw AIMessage (for token usage) next to the parsed object.
            # function_calling + our own Pydantic validation keeps range checks like 1 <= score <= 10.
            self._runnables[key] = chat.with_structured_output(schema, method="function_calling", include_raw=True)
        return self._runnables[key]

    def structured(self, schema: type[T], system: str, user: str, *, role: Role) -> tuple[T, dict]:
        if not self.settings.openai_api_key:
            raise LLMError("OPENAI_API_KEY is not set. Add it to .env, or run with LLM_PROVIDER=fake for an offline demo.")

        runnable = self._runnable(schema, role)
        messages = [SystemMessage(content=system), HumanMessage(content=user)]
        attempts = self.settings.llm_max_attempts
        try:
            for attempt in Retrying(
                stop=stop_after_attempt(attempts),
                wait=wait_exponential(multiplier=1, min=1, max=20),
                retry=retry_if_exception_type(_RETRYABLE),
                reraise=True,
            ):
                with attempt:
                    result = runnable.invoke(messages)
                    if result.get("parsing_error") or result.get("parsed") is None:
                        raise StructuredOutputError(str(result.get("parsing_error") or "empty structured output"))
        except openai.AuthenticationError as exc:
            raise LLMError("OpenAI rejected the API key. Check OPENAI_API_KEY.") from exc
        except _RETRYABLE as exc:
            raise LLMError(f"{role} call failed after {attempts} attempts: {exc}") from exc
        except openai.OpenAIError as exc:  # bad request, model not found, ...
            raise LLMError(f"OpenAI error during {role} call: {exc}") from exc

        meta = getattr(result["raw"], "usage_metadata", None) or {}
        usage = make_usage(self.model_for(role), meta.get("input_tokens", 0), meta.get("output_tokens", 0), self.settings)
        return result["parsed"], usage


def get_llm(settings: Settings) -> LLMClient:
    if settings.llm_provider == "fake":
        from agent.fake_llm import FakeLLM  # local import: only needed for offline runs

        return FakeLLM(settings)
    if settings.llm_provider == "openai":
        return OpenAIClient(settings)
    raise ValueError(f"Unknown LLM_PROVIDER '{settings.llm_provider}' (use 'openai' or 'fake').")
