"""Current-activity broadcasting with pluggable sinks.

The terminal sink is built in; the WebSocket broadcaster (ws_sink) ships in the
base for dashboards/overlays; messaging modules can add their own (e.g. Discord
presence). A sink is any callable taking the status payload dict.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from elifelse.textutils import print_system

Sink = Callable[[dict[str, Any]], None]


def terminal_sink(payload: dict[str, Any]) -> None:
    details = payload.get("details") or {}
    suffix = f" ({details})" if details else ""
    print_system(f"status: {payload['activity']}{suffix}")


class StatusTracker:
    def __init__(self, clock: Callable[[], datetime] = datetime.now) -> None:
        self._clock = clock
        self.sinks: list[Sink] = []
        self.activity = "idle"
        self.details: dict[str, Any] = {}
        self.started: datetime | None = None
        self.previous: str | None = None

    def add_sink(self, sink: Sink) -> None:
        self.sinks.append(sink)

    def set_activity(self, activity: str, details: dict[str, Any] | None = None) -> None:
        now = self._clock()
        self.previous = self.activity
        self.activity = activity
        self.details = details or {}
        self.started = now
        payload = {
            "type": "status_update",
            "timestamp": now.isoformat(),
            "activity": activity,
            "details": self.details,
            "previous": self.previous,
        }
        for sink in self.sinks:
            try:
                sink(payload)
            except Exception as e:  # a broken sink must never take down the loop
                print_system(f"status sink error: {e}")
