"""Last-used timestamps per activity (and per subject), with 'time ago' menu lines."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from elifelse.textutils import format_time_ago

# Outcome statuses
COMPLETED = "completed"
AWAITING_RESPONSE = "awaiting_response"
NO_RESPONSE = "no_response"


class ActivityTracker:
    def __init__(self, clock: Callable[[], datetime] = datetime.now) -> None:
        self._clock = clock
        # {activity_key: {subject: {"time": iso, "status": str}}}; "" = no subject
        self.records: dict[str, dict[str, dict[str, str]]] = {}

    def record_start(self, key: str, subject: str = "") -> None:
        self.records.setdefault(key, {})[subject] = {
            "time": self._clock().isoformat(),
            "status": "in_progress",
        }

    def record_complete(self, key: str, subject: str = "", status: str = COMPLETED) -> None:
        self.records.setdefault(key, {})[subject] = {
            "time": self._clock().isoformat(),
            "status": status,
        }

    def last_used(self, key: str, subject: str | None = None) -> datetime | None:
        entries = self.records.get(key, {})
        if not entries:
            return None
        if subject is not None:
            rec = entries.get(subject)
            return datetime.fromisoformat(rec["time"]) if rec else None
        return max(datetime.fromisoformat(r["time"]) for r in entries.values())

    def status_line(self, key: str, subject: str | None = None) -> str:
        """Menu status line, e.g. 'last: 2 hours ago'. Empty if never used."""
        last = self.last_used(key, subject)
        if last is None:
            return ""
        delta = (self._clock() - last).total_seconds()
        return f"last: {format_time_ago(delta)}"

    def to_dict(self) -> dict[str, Any]:
        return {"records": self.records}

    def from_dict(self, data: dict[str, Any]) -> None:
        self.records = data.get("records", {})
