"""Pre-menu interrupts + wake hooks.

Modules (and the day cycle) register checks that run at the top of every loop
iteration, before the menu — bedtime, calendar reminders, scheduled streams.
A hook returns a note string (or None); it may also run a whole flow itself.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

PreMenuHook = Callable[[], Awaitable[str | None]]
OnWakeHook = Callable[[], Awaitable[str | None]]


class Scheduler:
    def __init__(self) -> None:
        self.pre_menu_hooks: list[PreMenuHook] = []
        self.on_wake_hooks: list[OnWakeHook] = []

    def add_pre_menu_hook(self, hook: PreMenuHook) -> None:
        self.pre_menu_hooks.append(hook)

    def add_on_wake_hook(self, hook: OnWakeHook) -> None:
        self.on_wake_hooks.append(hook)

    async def run_pre_menu(self) -> list[str]:
        notes = []
        for hook in self.pre_menu_hooks:
            result = await hook()
            if result:
                notes.append(result)
        return notes

    async def run_on_wake(self) -> list[str]:
        notes = []
        for hook in self.on_wake_hooks:
            result = await hook()
            if result:
                notes.append(result)
        return notes
