"""Nap — the reference example for delegating to a framework subsystem.

The activity only picks a duration (schema-constrained); the actual sleeping —
chunked waits, message interrupts, the "wake up or keep sleeping?" ask — lives
in the day cycle, where the clock is injectable and tested.

Naps work with or without a schedule. When the agent sleeps, durations that
would run into the night are dropped from the menu and an early-night option is
added, so a nap can never strand it halfway into its own sleep window. When
sleeping is off there is no night to collide with, so every duration is offered.

Past night_start the activity stops being a nap at all: the menu entry reads
"Go to bed" and picking it starts the night, skipping the duration sub-menu.
That is the whole replacement for a scheduled bedtime. Nothing sends the agent
to bed, it just gets an option to go, and takes it when it's ready.
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

    def _minutes_left(self, ctx: ActivityContext) -> int | None:
        """Minutes before a nap would collide with the night, or None if it
        can't. A scheduled bedtime is the hard edge when there is one; without
        one the night window is, since a nap that runs into it becomes the
        night's sleep anyway."""
        daycycle = ctx.app.daycycle
        if daycycle.has_bedtime:
            return daycycle.minutes_until_bedtime()
        if ctx.app.config.day_cycle.enabled:
            if daycycle.in_night_window(ctx.app.clock()):
                return 0
            return int(daycycle.seconds_until(ctx.app.config.day_cycle.night_start) // 60)
        return None

    def _options(self, ctx: ActivityContext) -> tuple[list[str], list[str]]:
        """(values, labels) for the duration menu. Values are minutes as
        strings, plus the EARLY_NIGHT sentinel when the agent can sleep."""
        config = ctx.app.config.day_cycle
        durations = list(config.nap_durations)
        left = self._minutes_left(ctx)
        if left is not None:
            # Anything that would run into the night is not offered; the
            # early-night option covers that case properly instead.
            durations = [m for m in durations if m < left]

        values = [str(m) for m in durations]
        labels = [_label(m) for m in durations]
        if config.enabled:
            values.append(EARLY_NIGHT)
            if config.wake_mode == "fixed":
                label = f"Go to bed for the night (sleep until {format_time_12h(config.wake_time)})"
            else:
                # In alarm mode the wake hour isn't known yet; it gets picked
                # on the way to bed, so promising one here would be a guess.
                label = "Go to bed for the night"
            labels.append(label)
        return values, labels

    def available(self, ctx: ActivityContext) -> bool:
        if ctx.app.daycycle is None:
            return False
        values, _ = self._options(ctx)
        return bool(values)  # nothing left to offer = nothing to show

    def _is_night(self, ctx: ActivityContext) -> bool:
        config = ctx.app.config.day_cycle
        if not config.enabled:
            return False
        return ctx.app.daycycle.in_night_window(ctx.app.clock())

    def get_menu_label(self, ctx: ActivityContext) -> str:
        # Past night_start a rest means the night, so the entry says so. This
        # is the only nudge toward bed the agent gets, and it only shows up on
        # the menu, where it's choosing what to do anyway.
        return "Go to bed" if self._is_night(ctx) else self.menu_label

    async def run(self, ctx: ActivityContext) -> str:
        config = ctx.app.config.day_cycle
        if self._is_night(ctx):
            # The menu entry read "Go to bed", so that is what was picked. No
            # duration sub-menu: there is nothing to choose between.
            ctx.set_status("going to bed")
            print_system("nap — going to bed for the night")
            return await ctx.app.daycycle.night_sleep()

        values, labels = self._options(ctx)

        prompt = "You're feeling drowsy. How long do you want to nap?"
        if config.enabled and len(values) - 1 < len(config.nap_durations):
            # Some durations were dropped, so say why: the shorter menu should
            # read as a reason rather than an omission.
            if ctx.app.daycycle.has_bedtime:
                near = f"it's getting close to your {format_time_12h(config.bedtime)} bedtime"
            else:
                near = f"the night starts at {format_time_12h(config.night_start)}"
            prompt = (
                f"You're feeling drowsy, and {near}. How long do you want to nap?"
            )

        choice = await ctx.choose(prompt, values, labels=labels)
        if choice == EARLY_NIGHT:
            # Same destination as the "Go to bed" entry, reached from the
            # duration menu instead, so it reads the same in the log.
            ctx.set_status("going to bed")
            print_system("nap — going to bed for the night")
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
