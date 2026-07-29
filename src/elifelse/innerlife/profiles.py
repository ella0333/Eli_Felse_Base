"""Relationship profiles — one JSON file per person under data/profiles/.

Updated from post-chat surveys: how the agent currently feels about someone,
with a short history. Read back by chat activities to color the prompt.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from elifelse.trackers.stats import atomic_write_json

MAX_HISTORY = 50


class ProfileManager:
    def __init__(self, profiles_dir: Path, clock: Callable[[], datetime] = datetime.now) -> None:
        self.dir = profiles_dir
        self._clock = clock

    def _path(self, subject: str) -> Path:
        safe = re.sub(r"[^a-z0-9_-]+", "_", subject.strip().lower()) or "unknown"
        return self.dir / f"{safe}.json"

    def get(self, subject: str) -> dict[str, Any] | None:
        path = self._path(subject)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def record_feeling(self, subject: str, feeling: str, emotion: str = "") -> dict[str, Any]:
        now = self._clock().isoformat()
        profile = self.get(subject) or {
            "subject": subject,
            "current_feeling": "",
            "history": [],
            "interactions": 0,
        }
        profile["current_feeling"] = feeling
        profile["interactions"] = int(profile.get("interactions", 0)) + 1
        profile["last_interaction"] = now
        history = profile.setdefault("history", [])
        history.append({"time": now, "feeling": feeling, "emotion": emotion})
        del history[:-MAX_HISTORY]
        atomic_write_json(self._path(subject), profile)
        return profile
