"""The Activity interface — the contract every module implements.

Additions to this interface are fine within a major version of the base;
breaking changes bump the major. Modules declare `requires_base` and are
skipped (with a clear message) when incompatible, instead of crashing mid-loop.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from elifelse.activities.ctx import ActivityContext
    from elifelse.persona import Persona


class Activity(ABC):
    # ~~~ identity ~~~
    key: str = ""                  # "chess"
    menu_label: str = ""           # "Play Chess"

    # ~~~ requirements ~~~
    requires: list[str] = []       # config keys this activity needs (empty = key-free)
    requires_base: str = ""        # base version range, e.g. ">=0.1,<1"

    # ~~~ behavior declarations ~~~
    schemas: dict[str, dict[str, Any]] = {}  # module schemas, registered at load
    isolate_context: bool = False  # snapshot/restore context around it (games, long reads)
    memory_mode: str = "standard"  # "standard" or "game_batch" (3-msg merge, no classifier)
    memory_rules: str = ""         # extraction guidance ("" = base default)
    survey: str | None = None      # survey type after the activity, or None

    def get_menu_label(self, ctx: ActivityContext) -> str:
        """Menu label for this activity. Override for dynamic labels."""
        return self.menu_label

    def get_status(self, ctx: ActivityContext) -> str:
        """One menu status line, e.g. '3 unread messages'. Default: 'last used' time."""
        return ctx.app.activity_tracker.status_line(self.key)

    def get_prompt(self, persona: Persona) -> str:
        """The activity's system prompt. '' = keep the base prompt."""
        return ""

    def get_subject(self, ctx: ActivityContext) -> str:
        """Subject for summaries/surveys/profiles — a person's name for chats.
        '' = just use the activity label."""
        return ""

    def format_transcript(self, messages: list[dict[str, Any]]) -> str | None:
        """Optional transcript formatter for summaries. None = default formatting."""
        return None

    def available(self, ctx: ActivityContext) -> bool:
        """Hide from the menu when False (e.g. daily limit exhausted)."""
        return True

    async def startup(self, ctx: ActivityContext) -> None:
        """Optional service init (logins, bridges, checks) at app startup."""
        return None

    @abstractmethod
    async def run(self, ctx: ActivityContext) -> str:
        """The activity's own loop. Returns the note shown on the next menu."""
