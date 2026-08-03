"""Nap — the reference example for delegating to a framework subsystem.

The activity only picks a duration (schema-constrained); the actual sleeping —
chunked waits, message interrupts, the "wake up or keep sleeping?" ask — lives
in the day cycle, where the clock is injectable and tested.

Naps work with or without a schedule. When the day cycle is on, durations that
would run past bedtime are dropped from the menu and an early-night option is
added, so a nap can never strand the agent halfway into its own sleep window.
When it's off there is no bedtime to collide with, so every duration is offered.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from elifelse.activities.base import Activity
from elifelse.textutils import format_time_12h, print_system

if TYPE_CHECKING:
    from elifelse.activities.ctx import ActivityContext

EARLY_NIGHT = "early_night"  # sentinel option value: go to bed now, not a nap


def _label(minutes: int) -> str:
    if minutes >= 60 and minutes % 60 == 0:
        h = minutes // 60
        return f"{h} hour{'s' if h != 1 else ''}"
    return f"{minutes} minute{'s' if minutes != 1 else ''}"


class NapActivity(Activity):
    key = "nap"
    menu_label = "Take a nap"
    requires_base = ">=0.2,<1"
    survey = "simple"

    def _options(self, ctx: ActivityContext) -> tuple[list[str], list[str]]:
        """(values, labels) for the duration menu. Values are minutes as
        strings, plus the EARLY_NIGHT sentinel when there's a bedtime."""
        config = ctx.app.config.day_cycle
        durations = list(config.nap_durations)
        if config.enabled:
            # Anything that would run into the sleep window is not offered;
            # the early-night option covers that case properly instead.
            left = ctx.app.daycycle.minutes_until_bedtime()
            durations = [m for m in durations if m < left]

        values = [str(m) for m in durations]
        labels = [_label(m) for m in durations]
        if config.enabled:
            values.append(EARLY_NIGHT)
            labels.append(f"Go to bed early (sleep until {format_time_12h(config.wake_time)})")
        return values, labels

    def available(self, ctx: ActivityContext) -> bool:
        if ctx.app.daycycle is None:
            return False
        values, _ = self._options(ctx)
        return bool(values)  # nothing left to offer = nothing to show

    async def run(self, ctx: ActivityContext) -> str:
        config = ctx.app.config.day_cycle
        values, labels = self._options(ctx)

        prompt = "You're feeling drowsy. How long do you want to nap?"
        if config.enabled and len(values) - 1 < len(config.nap_durations):
            # Some durations were dropped, so say why: the shorter menu should
            # read as a reason rather than an omission.
            prompt = (
                f"You're feeling drowsy, and it's getting close to your "
                f"{format_time_12h(config.bedtime)} bedtime. How long do you "
                f"want to nap?"
            )

        choice = await ctx.choose(prompt, values, labels=labels)
        if choice == EARLY_NIGHT:
            ctx.set_status("going to bed early")
            print_system("nap — going to bed early")
            return await ctx.app.daycycle.night_sleep()

        minutes = int(choice)
        ctx.set_status(f"napping ({_label(minutes)})")
        print_system(f"nap — {_label(minutes)}")

        # real_time: false makes the nap return instantly. The mock demo sets
        # it so a three-iteration run doesn't block for a real twenty minutes.
        wait = minutes if ctx.config.get("real_time", True) else 0
        result = await ctx.app.daycycle.nap(wait)
        if result == "interrupted":
            return "Your nap was cut short."
        if result != "completed":
            return result  # bedtime landed mid-nap; pass the day cycle's wake note on
        return f"You napped for {_label(minutes)} and woke up on your own."
