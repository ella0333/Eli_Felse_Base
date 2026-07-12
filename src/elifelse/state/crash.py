"""Crash context: written at the top of every loop iteration so a crash (or
Ctrl+C) can be resumed from the last known state."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from elifelse.trackers.stats import atomic_write_json

if TYPE_CHECKING:
    from elifelse.app import App

CRASH_VERSION = 1


def capture_state(app: App, note: str = "") -> dict[str, Any]:
    """The resumable state of the agent — shared by crash context and saves."""
    return {
        "crash_version": CRASH_VERSION,
        "saved_at": app.clock().isoformat(),
        "note": note,
        "system_prompt": app.provider.context.system_prompt,
        "context_messages": list(app.provider.context.messages),
        "context_timestamps": list(app.provider.context.timestamps),
        "activity_tracker": app.activity_tracker.to_dict(),
        "current_activity": app.status.activity,
        "environment": app.environment.current_key if app.environment else None,
        "emotion": app.innerlife.current_emotion if app.innerlife else "",
    }


def apply_state(app: App, data: dict[str, Any]) -> None:
    """Restore captured state — shared by crash recovery and save loading."""
    from collections import deque

    app.provider.context.messages = deque(data.get("context_messages", []))
    app.provider.context.timestamps = deque(data.get("context_timestamps", []))
    app.provider.context.set_system_prompt(data.get("system_prompt", ""))
    app.activity_tracker.from_dict(data.get("activity_tracker", {}))
    if app.environment is not None and data.get("environment"):
        app.environment.set_current(data["environment"])
    if app.innerlife is not None and data.get("emotion"):
        app.innerlife.current_emotion = data["emotion"]


def write_crash_context(app: App, note: str = "") -> None:
    atomic_write_json(app.paths.crash_context, capture_state(app, note))


def load_crash_context(app: App) -> dict[str, Any] | None:
    path = app.paths.crash_context
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def recover_from_crash(app: App, data: dict[str, Any]) -> str:
    """Restore state from a crash context. Returns the recovery note."""
    apply_state(app, data)
    saved_at = data.get("saved_at", "recently")
    return (
        "[The system restarted unexpectedly. You're picking up where you left off "
        f"(last state saved {saved_at}).]"
    )


def clear_crash_context(app: App) -> None:
    try:
        app.paths.crash_context.unlink(missing_ok=True)
    except OSError:
        pass
