"""Nap — the reference example for delegating to a framework subsystem.

The activity only picks a duration (schema-constrained); the actual sleeping —
chunked waits, message interrupts, the "wake up or keep sleeping?" ask — lives
in the day cycle, where the clock is injectable and tested.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from elifelse.activities.base import Activity
from elifelse.textutils import print_system

if TYPE_CHECKING:
    from elifelse.activities.ctx import ActivityContext


def _label(minutes: int) -> str:
    if minutes >= 60 and minutes % 60 == 0:
        h = minutes // 60
        return f"{h} hour{'s' if h != 1 else ''}"
    return f"{minutes} minutes"


class NapActivity(Activity):
    key = "nap"
    menu_label = "Take a nap"
    requires_base = ">=0.1,<1"
    survey = "simple"

    def available(self, ctx: ActivityContext) -> bool:
        return ctx.app.daycycle is not None  # naps need the day cycle enabled

    async def run(self, ctx: ActivityContext) -> str:
        durations = ctx.app.config.day_cycle.nap_durations
        options = [_label(m) for m in durations]
        choice = await ctx.choose(
            "You're feeling drowsy. How long do you want to nap?", options
        )
        minutes = durations[options.index(choice)]

        ctx.set_status(f"napping ({_label(minutes)})")
        print_system(f"nap — {_label(minutes)}")
        result = await ctx.app.daycycle.nap(minutes)
        if result == "interrupted":
            return "Your nap was cut short."
        return f"You napped for {_label(minutes)} and woke up on your own."
