"""Lifetime stats counters (activities done, messages, days alive...)."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any


def atomic_write_json(path: Path, data: Any) -> None:
    """temp file + os.replace so a crash can never corrupt the file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, path)


class StatsTracker:
    def __init__(self, path: Path, clock: Callable[[], datetime] = datetime.now) -> None:
        self.path = path
        self._clock = clock
        self.data: dict[str, Any] = {"counters": {}, "first_start": None, "total_sessions": 0}
        self.load()

    def load(self) -> None:
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        if not self.data.get("first_start"):
            self.data["first_start"] = self._clock().isoformat()

    def save(self) -> None:
        atomic_write_json(self.path, self.data)

    def session_started(self) -> None:
        self.data["total_sessions"] = int(self.data.get("total_sessions", 0)) + 1
        self.save()

    def increment(self, name: str, by: int = 1) -> None:
        counters = self.data.setdefault("counters", {})
        counters[name] = int(counters.get(name, 0)) + by
        self.save()

    def get(self, name: str) -> int:
        return int(self.data.get("counters", {}).get(name, 0))

    @property
    def days_since_first_start(self) -> int:
        first = datetime.fromisoformat(self.data["first_start"])
        return max(0, (self._clock() - first).days)
