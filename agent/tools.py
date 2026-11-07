"""The mock `schedule_post` tool.

A real version would call the LinkedIn / X APIs (or Buffer, Hootsuite, ...).
This one appends to a local JSON file, which is enough to prove the flow:
nothing is "published" unless a human approved it.

It is a LangChain tool so it has a typed, documented schema and could later be
bound to an LLM, but in this graph it is called deterministically by the
`schedule` node, never chosen by the model.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from langchain_core.tools import BaseTool, tool

_FILE_LOCK = threading.Lock()


def make_schedule_tool(schedule_file: str) -> BaseTool:
    path = Path(schedule_file)

    @tool
    def schedule_post(platform: str, text: str, scheduled_at_utc: str, run_id: str, source_url: str = "") -> dict:
        """Schedule a social media post for publishing at a UTC time (mock: writes to a local JSON file).

        Idempotent per (run_id, platform): calling it twice for the same run returns
        the existing entry instead of scheduling a duplicate post.
        """
        with _FILE_LOCK:
            entries = json.loads(path.read_text()) if path.exists() else []
            for entry in entries:
                if entry["run_id"] == run_id and entry["platform"] == platform:
                    return entry

            entry = {
                "id": str(uuid.uuid4()),
                "run_id": run_id,
                "platform": platform,
                "text": text,
                "source_url": source_url,
                "scheduled_at_utc": scheduled_at_utc,
                "status": "scheduled",
                "created_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            entries.append(entry)

            # Write to a temp file then rename, so a crash never leaves half-written JSON.
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(entries, indent=2, ensure_ascii=False))
            os.replace(tmp, path)
            return entry

    return schedule_post
