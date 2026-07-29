"""Small text helpers shared across the framework. ASCII-safe terminal output."""

from __future__ import annotations

import re
import sys

# Matches placeholder/non-substantive content like "...", "[...]", "(...)" etc.
PLACEHOLDER_RE = re.compile(r"^[\[\(]?[.\u2026]{2,}[\]\)]?\.?$")

# Harmony-style channel tags some models leak into output.
_HARMONY_RE = re.compile(r"<\|[^|]*\|>")


def print_system(text: str) -> None:
    """Print a framework status line, ASCII-safe (Windows terminals may not be UTF-8)."""
    line = f"[system] {text}"
    try:
        print(line)
    except UnicodeEncodeError:
        enc = sys.stdout.encoding or "ascii"
        print(line.encode(enc, errors="replace").decode(enc))


def strip_harmony_tags(text: str) -> str:
    """Remove leaked harmony/channel formatting tags from model output."""
    return _HARMONY_RE.sub("", text).strip()


def is_placeholder(text: str) -> bool:
    """True if the text is empty or a '...'-style placeholder."""
    return not text.strip() or bool(PLACEHOLDER_RE.match(text.strip()))


def clean_thinking(text: str) -> str:
    """Strip mimicked '[Thinking: ...]' wrappers (models copy the brackets from context)."""
    t = text.strip()
    nest = 0
    while t.startswith("[Thinking:"):
        t = t[len("[Thinking:"):].strip()
        nest += 1
    for _ in range(nest):
        if t.endswith("]"):
            t = t[:-1].strip()
    return t


def format_time_12h(hhmm: str) -> str:
    """Convert 24h 'HH:MM' to 12-hour AM/PM display, e.g. '22:00' -> '10:00 PM'."""
    h, m = int(hhmm.split(":")[0]), int(hhmm.split(":")[1])
    suffix = "AM" if h < 12 else "PM"
    display_h = h % 12 or 12
    return f"{display_h}:{m:02d} {suffix}"


def format_time_ago(seconds: float) -> str:
    """Human 'time ago' for menu status lines."""
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        m = int(seconds // 60)
        return f"{m} minute{'s' if m != 1 else ''} ago"
    if seconds < 86400:
        h = int(seconds // 3600)
        return f"{h} hour{'s' if h != 1 else ''} ago"
    d = int(seconds // 86400)
    if d == 1:
        return "yesterday"
    return f"{d} days ago"
