"""Named saves — snapshots of the agent's resumable state, written atomically.

A save is the same shape as the crash context (context, tracker, environment,
emotion) plus a name and reason. The framework saves automatically at sleep,
pause, and stop; `elifelse run --load NAME` starts from one.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from elifelse.config import ConfigError
from elifelse.state.crash import apply_state, capture_state
from elifelse.textutils import print_system
from elifelse.trackers.stats import atomic_write_json

if TYPE_CHECKING:
    from pathlib import Path

    from elifelse.app import App


def _sanitize(name: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "_", name.strip().lower()).strip("_") or "save"


def list_saves(saves_dir: Path) -> list[dict[str, Any]]:
    """Newest first: {file, name, reason, saved_at} per save. Needs no App —
    the CLI `elifelse saves` command uses this directly."""
    saves = []
    for path in sorted(saves_dir.glob("*.json"), reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        saves.append(
            {
                "file": path.name,
                "name": data.get("name", path.stem),
                "reason": data.get("reason", ""),
                "saved_at": data.get("saved_at", ""),
            }
        )
    return saves


class SaveSystem:
    def __init__(self, app: App) -> None:
        self.app = app

    async def save(self, reason: str, name: str = "") -> Path:
        label = _sanitize(name or reason)
        data = capture_state(self.app)
        data["name"] = name or reason
        data["reason"] = reason

        stamp = self.app.clock().strftime("%Y%m%d_%H%M%S")
        path = self.app.paths.saves / f"{stamp}_{label}.json"
        atomic_write_json(path, data)
        print_system(f"saved: {path.name}")
        return path

    def list_saves(self) -> list[dict[str, Any]]:
        return list_saves(self.app.paths.saves)

    def load(self, name: str) -> str:
        """Restore the newest save matching `name` (or an exact file name).
        Returns the note shown to the agent on the first menu."""
        for entry in self.list_saves():
            if entry["name"] == name or entry["file"] == name:
                path = self.app.paths.saves / entry["file"]
                apply_state(self.app, json.loads(path.read_text(encoding="utf-8")))
                print_system(f"loaded save: {entry['file']}")
                return (
                    f"[You loaded your save '{entry['name']}' from "
                    f"{entry['saved_at']}. Picking up from there.]"
                )
        available = ", ".join(sorted({s["name"] for s in self.list_saves()})) or "(none)"
        raise ConfigError(f"No save named '{name}'. Available saves: {available}")
