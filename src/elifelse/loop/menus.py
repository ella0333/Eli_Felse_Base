"""Menu construction. The base owns the frame (note line, lettered options,
time footer); each activity supplies its label + status line + availability.

Every choice put to the model (the main menu, bedtime, and every sub-menu an
activity asks through `ctx.choose()`) is built here and rendered the same
way: "A) label" lines, with the letters themselves as the schema enum. The
model answers with a letter and the base maps it back, so a label is never a
value the model has to reproduce."""

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
    mapping: dict[str, str]  # letter -> activity key (or option value, for sub-menus)


def letters_for(count: int) -> list[str]:
    """A, B, C ... Z, then AA, AB ... so a long list never runs out."""
    alphabet = string.ascii_uppercase
    letters: list[str] = []
    for i in range(count):
        if i < len(alphabet):
            letters.append(alphabet[i])
        else:
            first, second = divmod(i - len(alphabet), len(alphabet))
            letters.append(alphabet[first] + alphabet[second])
    return letters


def build_choice_menu(
    question: str,
    options: list[str],
    labels: list[str] | None = None,
    footer: str = "",
) -> Menu:
    """A lettered sub-menu, same frame as the main menu.

    `options` are the values the caller gets back; `labels` (defaulting to the
    options) are what the model reads. The letters list IS the choice enum.
    """
    labels = labels if labels is not None else options
    if len(labels) != len(options):
        raise ValueError("choose() needs one label per option")
    letters = letters_for(len(options))

    lines = [question, ""]
    lines += [f"{letter}) {label}" for letter, label in zip(letters, labels, strict=True)]
    if footer:
        lines += ["", footer]
    return Menu(
        text="\n".join(lines),
        letters=letters,
        mapping=dict(zip(letters, options, strict=True)),
    )


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
    for letter, entry in zip(letters_for(len(entries)), entries, strict=True):
        letters.append(letter)
        mapping[letter] = entry["key"]
        status = f" ({entry['status']})" if entry.get("status") else ""
        lines.append(f"{letter}) {entry['label']}{status}")

    lines.append("")
    lines.append(f"Current Time: {now.strftime('%I:%M %p')}")
    return Menu(text="\n".join(lines), letters=letters, mapping=mapping)


def build_bedtime_menu(bedtime: str) -> Menu:
    return build_choice_menu(
        f"It's {format_time_12h(bedtime)} — your bedtime. You're getting tired.",
        options=["sleep", "stay_up"],
        labels=[
            "Go to sleep for the night",
            "Stay up a while longer (you'll be reminded again in an hour)",
        ],
    )
