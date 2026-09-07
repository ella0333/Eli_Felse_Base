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


# Marks a main-menu letter that opens a group sub-menu rather than an activity.
GROUP_PREFIX = "group:"


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


def group_rows(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse entries sharing a `group` label into one row each.

    Ungrouped entries keep their own row. A group takes the position of its
    first member, so installing a second game does not move the line the agent
    already knows. The label itself is the group's identity: two modules that
    declare the same `menu_group` string land on the same line without either
    knowing the other exists.
    """
    rows: list[dict[str, Any]] = []
    by_group: dict[str, dict[str, Any]] = {}
    for entry in entries:
        group = entry.get("group") or ""
        if not group:
            rows.append({"group": "", "members": [entry]})
            continue
        row = by_group.get(group)
        if row is None:
            row = {"group": group, "members": []}
            by_group[group] = row
            rows.append(row)
        row["members"].append(entry)
    return rows


def _render_main_menu(
    rows: list[dict[str, Any]],
    note: str,
    now: datetime,
    notifications: str,
    blocked_key: str,
    blocked_note: str,
) -> Menu:
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
    for letter, row in zip(letters_for(len(rows)), rows, strict=True):
        members = row["members"]
        if not row["group"]:
            entry = members[0]
            status = f" ({entry['status']})" if entry.get("status") else ""
            if blocked_key and entry["key"] == blocked_key:
                lines.append(
                    f"{letter}) {entry['label']}{status} "
                    f"({blocked_note or 'unavailable this turn'})"
                )
                continue
            letters.append(letter)
            mapping[letter] = entry["key"]
            lines.append(f"{letter}) {entry['label']}{status}")
            continue

        # A group line names its members, so the agent can see what is behind
        # it without opening it.
        listing = ", ".join(member["label"] for member in members)
        label = f"{row['group']} ({listing})" if listing else row["group"]
        if all(member["key"] == blocked_key for member in members):
            # Blocking the only member blocks the whole line.
            lines.append(f"{label} ({blocked_note or 'unavailable this turn'})")
            continue
        letters.append(letter)
        mapping[letter] = f"{GROUP_PREFIX}{row['group']}"
        lines.append(f"{letter}) {label}")

    lines.append("")
    lines.append(f"Current Time: {now.strftime('%I:%M %p')}")
    return Menu(text="\n".join(lines), letters=letters, mapping=mapping)


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

    Entries carrying the same `group` label collapse into one line whose letter
    maps to `group:<label>`; the caller opens `build_group_menu()` on it to get
    the activity. Everything else about the frame is unchanged, so an agent
    only ever learns one way to answer.

    `blocked_key` is the activity picked last turn. Its line still shows, with
    `blocked_note` saying why it is off the table, but its letter is left out
    of the enum so the model cannot pick it again. Showing the line and the
    reason is the point: an option that silently vanished would read as the
    activity breaking. Never applied when it would leave nothing to choose,
    which for a group means the block only reaches the main menu when it would
    empty the group.
    """
    now = now or datetime.now()
    rows = group_rows(entries)
    menu = _render_main_menu(rows, note, now, notifications, blocked_key, blocked_note)
    if not menu.letters and blocked_key:
        menu = _render_main_menu(rows, note, now, notifications, "", "")
    return menu


def build_group_menu(
    group: str,
    members: list[dict[str, Any]],
    blocked_key: str = "",
    blocked_note: str = "",
) -> Menu:
    """The second level behind a grouped main-menu line.

    Same frame as every other menu: the group label is the question, members
    are lettered, and the letters are the enum. A member held back by the
    repeat rule still shows with its reason, exactly as it would on the main
    menu, so the agent sees why rather than watching an option disappear.
    """
    options: list[str] = []
    labels: list[str] = []
    blocked_lines: list[str] = []
    for member in members:
        status = f" ({member['status']})" if member.get("status") else ""
        if blocked_key and member["key"] == blocked_key and len(members) > 1:
            blocked_lines.append(
                f"{member['label']}{status} ({blocked_note or 'unavailable this turn'})"
            )
            continue
        options.append(member["key"])
        labels.append(f"{member['label']}{status}")

    menu = build_choice_menu(group, options=options, labels=labels)
    if blocked_lines:
        menu.text = "\n".join([menu.text, *blocked_lines])
    return menu


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
