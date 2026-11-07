"""Runtime configuration.

Every setting comes from an environment variable (a local `.env` file is loaded
automatically), so the same code runs on a laptop, in Docker and in CI.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


def _env(name: str, default: str) -> str:
    value = os.getenv(name)
    return value if value not in (None, "") else default


def _optional_float(name: str) -> float | None:
    value = os.getenv(name)
    return float(value) if value else None


@dataclass(frozen=True)
class Settings:
    # --- LLM ---
    llm_provider: str = "openai"          # "openai" or "fake" (offline, deterministic test double)
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"     # planner + writer
    judge_model: str = "gpt-4o-mini"      # critique node (can be a different model to reduce self-bias)
    llm_timeout_s: float = 60.0
    llm_max_attempts: int = 3
    # Optional price override (USD per 1M tokens) for models not in llm.PRICES.
    price_input_per_1m: float | None = None
    price_output_per_1m: float | None = None

    # --- Fetching and chunking ---
    fetch_timeout_s: float = 15.0
    fetch_max_attempts: int = 3
    allow_private_urls: bool = False      # SSRF guard: block localhost / private IPs by default
    chunk_max_chars: int = 1500
    max_source_chars: int = 12_000        # context budget sent to the LLM
    min_source_chars: int = 200

    # --- Quality loop ---
    pass_threshold: int = 7               # every score must be >= this to pass
    max_revisions: int = 2                # rewrite passes after the first draft

    # --- Scheduling (mock) ---
    schedule_file: str = "data/scheduled_posts.json"
    schedule_delay_minutes: int = 60

    @classmethod
    def from_env(cls) -> "Settings":
        model = _env("OPENAI_MODEL", "gpt-4o-mini")
        return cls(
            llm_provider=_env("LLM_PROVIDER", "openai").lower(),
            openai_api_key=_env("OPENAI_API_KEY", ""),
            openai_model=model,
            judge_model=_env("JUDGE_MODEL", model),
            llm_timeout_s=float(_env("LLM_TIMEOUT_S", "60")),
            llm_max_attempts=int(_env("LLM_MAX_ATTEMPTS", "3")),
            price_input_per_1m=_optional_float("PRICE_INPUT_PER_1M"),
            price_output_per_1m=_optional_float("PRICE_OUTPUT_PER_1M"),
            fetch_timeout_s=float(_env("FETCH_TIMEOUT_S", "15")),
            fetch_max_attempts=int(_env("FETCH_MAX_ATTEMPTS", "3")),
            allow_private_urls=_env("ALLOW_PRIVATE_URLS", "false").lower() == "true",
            chunk_max_chars=int(_env("CHUNK_MAX_CHARS", "1500")),
            max_source_chars=int(_env("MAX_SOURCE_CHARS", "12000")),
            min_source_chars=int(_env("MIN_SOURCE_CHARS", "200")),
            pass_threshold=int(_env("PASS_THRESHOLD", "7")),
            max_revisions=int(_env("MAX_REVISIONS", "2")),
            schedule_file=_env("SCHEDULE_FILE", "data/scheduled_posts.json"),
            schedule_delay_minutes=int(_env("SCHEDULE_DELAY_MINUTES", "60")),
        )


@lru_cache
def get_settings() -> Settings:
    return Settings.from_env()
