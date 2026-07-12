"""Menu construction. The base owns the frame (note line, lettered options,
time footer); each activity supplies its label + status line + availability."""

from __future__ import annotations

import string
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from elifelse.textutils import format_time_12h


@dataclass
class Menu:
    text: str
    letters: list[str]
    mapping: dict[str, str]  # letter -> activity key


def build_main_menu(
    entries: list[dict[str, Any]],
    note: str = "",
    now: datetime | None = None,
    notifications: str = "",
) -> Menu:
    """Assemble the menu text and the letter->activity mapping.

    The letters list IS the choice enum: whatever the model answers, only these
    exact letters can ever come back from the provider.
    """
    now = now or datetime.now()
    letters: list[str] = []
    mapping: dict[str, str] = {}
    lines: list[str] = []

    if note:
        lines.append(note)
        lines.append("")
    if notifications:
        lines.append(notifications)
        lines.append("")

    lines.append("What would you like to do next?")
    for i, entry in enumerate(entries):
        letter = string.ascii_uppercase[i]
        letters.append(letter)
        mapping[letter] = entry["key"]
        status = f" ({entry['status']})" if entry.get("status") else ""
        lines.append(f"{letter}) {entry['label']}{status}")

    lines.append("")
    lines.append(f"Current Time: {now.strftime('%I:%M %p')}")
    return Menu(text="\n".join(lines), letters=letters, mapping=mapping)


def build_bedtime_menu(bedtime: str) -> str:
    return (
        f"It's {format_time_12h(bedtime)} — your bedtime. You're getting tired.\n"
        "sleep) Go to sleep for the night\n"
        "stay_up) Stay up a while longer (you'll be reminded again in an hour)"
    )
