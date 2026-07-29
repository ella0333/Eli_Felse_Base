"""Daily-limits utility any activity can use ("1 remaining today" pattern).

Counters reset at the date boundary and persist across restarts.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from elifelse.trackers.stats import atomic_write_json


class DailyLimits:
    def __init__(self, path: Path, clock: Callable[[], datetime] = datetime.now) -> None:
        self.path = path
        self._clock = clock
        self.data: dict = {"date": self._today(), "used": {}}
        if path.exists():
            try:
                self.data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        self._roll()

    def _today(self) -> str:
        return self._clock().strftime("%Y-%m-%d")

    def _roll(self) -> None:
        if self.data.get("date") != self._today():
            self.data = {"date": self._today(), "used": {}}
            self._save()

    def _save(self) -> None:
        atomic_write_json(self.path, self.data)

    def used(self, key: str) -> int:
        self._roll()
        return int(self.data["used"].get(key, 0))

    def remaining(self, key: str, limit: int) -> int:
        return max(0, limit - self.used(key))

    def use(self, key: str, amount: int = 1) -> None:
        self._roll()
        self.data["used"][key] = self.used(key) + amount
        self._save()
