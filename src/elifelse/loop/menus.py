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
from datetime import datetime, timedelta
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


async def ask_menu(app: Any, menu: Menu) -> str | None:
    """Show a menu, put it to the agent, and return the option it picked.

    None when the answer was unusable, which every caller handles its own way.
    This is the counterpart to ctx.choose() for menus the framework itself
    asks: printing before the call is the point, so the terminal always shows
    what the model was shown rather than a silent pause on "thinking...".
    """
    print(f"\n{menu.text}")
    result = await app.provider.generate(menu.text, schema=app.schemas.menu(menu.letters))
    if result.get("thinking"):
        print(f"\nThinking: {result['thinking']}")
    letter = str(result.get("choice", "")).strip().upper()
    if letter not in menu.mapping:
        return None
    print(f"Choice: {letter}")
    return menu.mapping[letter]


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
    blocked_key: str = "",
    blocked_note: str = "",
) -> Menu:
    """Assemble the menu text and the letter->activity mapping.

    The letters list IS the choice enum: whatever the model answers, only these
    exact letters can ever come back from the provider.

    `blocked_key` is the activity picked last turn. Its line still shows, with
    `blocked_note` saying why it is off the table, but its letter is left out
    of the enum so the model cannot pick it again. Showing the line and the
    reason is the point: an option that silently vanished would read as the
    activity breaking. Never applied when it would leave nothing to choose.
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

    if len(entries) < 2:
        blocked_key = ""

    lines.append("What would you like to do next?")
    for letter, entry in zip(letters_for(len(entries)), entries, strict=True):
        status = f" ({entry['status']})" if entry.get("status") else ""
        if blocked_key and entry["key"] == blocked_key:
            note_text = blocked_note or "unavailable this turn"
            lines.append(f"{letter}) {entry['label']}{status} ({note_text})")
            continue
        letters.append(letter)
        mapping[letter] = entry["key"]
        lines.append(f"{letter}) {entry['label']}{status}")

    lines.append("")
    lines.append(f"Current Time: {now.strftime('%I:%M %p')}")
    return Menu(text="\n".join(lines), letters=letters, mapping=mapping)


def _sleep_length(minutes: int) -> str:
    """Whole hours only. The trailing minutes were noise on a menu whose only
    job is "roughly how long will I be out", and truncating rather than
    rounding never promises more sleep than the option actually gives."""
    hours = max(0, minutes) // 60
    return f"{hours} hour{'s' if hours != 1 else ''} of sleep"


def build_alarm_menu(now: datetime, alarm_hours: list[int]) -> tuple[Menu, list[int]]:
    """The wake-hour picker, one entry per hour in `alarm_hours`.

    Returns the menu and the hours in menu order, so the caller maps the chosen
    option straight to an hour instead of rebuilding the same list and risking
    the two drifting apart. Every hour is always offered: there is no cap on
    how far out an alarm can be set, and an agent that wants to sleep for
    seventeen hours is allowed to.
    """
    options: list[str] = []
    labels: list[str] = []
    hours: list[int] = []
    for index, hour in enumerate(alarm_hours):
        alarm_at = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if alarm_at <= now:
            alarm_at += timedelta(days=1)
        minutes = int((alarm_at - now).total_seconds() / 60)
        options.append(str(index))
        labels.append(f"{format_time_12h(f'{hour:02d}:00')} ({_sleep_length(minutes)})")
        hours.append(hour)

    menu = build_choice_menu(
        "You're settling in for the night. What time do you want to wake up?",
        options=options,
        labels=labels,
        footer=f"Current Time: {now.strftime('%I:%M %p')}",
    )
    return menu, hours


def build_bedtime_menu(bedtime: str) -> Menu:
    return build_choice_menu(
        f"It's {format_time_12h(bedtime)} — your bedtime. You're getting tired.",
        options=["sleep", "stay_up"],
        labels=[
            "Go to sleep for the night",
            "Stay up a while longer (you'll be reminded again in an hour)",
        ],
    )
