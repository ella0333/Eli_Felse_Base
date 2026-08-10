"""The day cycle: night, night sleep, waking up, naps, budget sleep.

There are two ways the agent can end its day. With a scheduled bedtime it gets
the bedtime menu (sleep now / stay up an hour) once the hour arrives. With no
bedtime, which is the default, nothing interrupts it: from `night_start` the
nap activity reads "Go to bed" and it turns in when it chooses to. A bedtime
is something the agent counts down to, so it spends the evening anticipating
it instead of doing anything else, which is why it is opt-in.

Waking works the same two ways. In "alarm" mode it picks its own wake hour
from a menu as it settles in; in "fixed" mode it always wakes at wake_time.

Night sleep is where quiet maintenance happens: save, settle background
extraction, consolidate facts, back up the data dir — then one long sleep
until wake time, then on-wake hooks and a fresh-morning note for the first menu.

Everything uses the injectable app.clock/app.sleep_fn, so tests can run a
whole "day" in milliseconds.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from elifelse.loop.menus import build_alarm_menu, build_bedtime_menu, build_choice_menu
from elifelse.textutils import format_time_12h, print_system

if TYPE_CHECKING:
    from elifelse.app import App

STAY_UP_DEFER = timedelta(hours=1)
NAP_CHECK_SECONDS = 30


def _parse_hhmm(value: str) -> tuple[int, int]:
    h, m = value.split(":")
    return int(h), int(m)


def _between(now: datetime, start: str, end: str) -> bool:
    """Is `now` inside the [start, end) window, which may cross midnight."""
    start_h, start_m = _parse_hhmm(start)
    end_h, end_m = _parse_hhmm(end)
    t = now.hour * 60 + now.minute
    lo = start_h * 60 + start_m
    hi = end_h * 60 + end_m
    if lo == hi:
        return False
    if lo < hi:  # window inside one day (e.g. 01:00 -> 09:00)
        return lo <= t < hi
    return t >= lo or t < hi  # window crosses midnight (e.g. 22:00 -> 08:00)


class DayCycle:
    def __init__(self, app: App) -> None:
        self.app = app
        self.config = app.config.day_cycle
        self._defer_until: datetime | None = None

    def register(self) -> None:
        # Only a scheduled bedtime needs to interrupt the menu. Without one
        # there is nothing to interrupt with, so nothing gets wired up.
        if self.has_bedtime:
            self.app.scheduler.add_pre_menu_hook(self.check_bedtime)

    @property
    def has_bedtime(self) -> bool:
        """Is there a scheduled bedtime, as opposed to sleeping when it likes."""
        return self.config.enabled and bool(self.config.bedtime)

    # ~~~ time math ~~~
    def night_ends_at(self) -> str:
        """The hour the night is over, as 'HH:MM'.

        In fixed mode that is the wake time. In alarm mode the wake hour is not
        known until the agent picks one, so the earliest hour it could pick
        stands in: before then it is still night, after then it might be up.
        """
        if self.config.wake_mode == "fixed":
            return self.config.wake_time
        return f"{min(self.config.alarm_hours):02d}:00"

    def in_night_window(self, now: datetime) -> bool:
        """Is it late enough that resting means the night, not a nap.

        Runs from night_start to night_ends_at. Unlike in_sleep_window this
        does not force anything: it only changes what the nap activity offers.
        """
        return _between(now, self.config.night_start, self.night_ends_at())

    def in_sleep_window(self, now: datetime) -> bool:
        if not self.config.bedtime:
            return False
        return _between(now, self.config.bedtime, self.config.wake_time)

    def minutes_until_bedtime(self) -> int:
        """Whole minutes until the next bedtime; 0 once inside the sleep window.

        Used to keep nap durations from running past bedtime. Meaningless when
        there is no scheduled bedtime, so callers check `has_bedtime` first.
        """
        if self.in_sleep_window(self.app.clock()):
            return 0
        return int(self.seconds_until(self.config.bedtime) // 60)

    def seconds_until(self, hhmm: str) -> float:
        now = self.app.clock()
        h, m = _parse_hhmm(hhmm)
        target = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return (target - now).total_seconds()

    # ~~~ bedtime ~~~
    async def check_bedtime(self) -> str | None:
        """Pre-menu hook: offer sleep in the sleep window (unless deferred)."""
        app = self.app
        now = app.clock()
        if not self.in_sleep_window(now):
            self._defer_until = None
            return None
        if self._defer_until is not None and now < self._defer_until:
            return None

        menu = build_bedtime_menu(self.config.bedtime)
        result = await app.provider.generate(menu.text, schema=app.schemas.menu(menu.letters))
        if menu.mapping.get(str(result.get("choice", "")).strip().upper()) == "sleep":
            return await self.night_sleep()
        # stay_up (or a failed response — never force the issue on an error)
        self._defer_until = now + STAY_UP_DEFER
        return "You decided to stay up a while longer."

    # ~~~ waking up ~~~
    async def pick_wake_time(self) -> str:
        """The hour this night ends, as 'HH:MM'.

        Fixed mode answers straight from config. Alarm mode puts the hours in
        `alarm_hours` to the agent as a menu and takes its pick, so a wake time
        it chose is the one thing about its schedule it never has to be told.
        A failed or nonsense answer falls back to wake_time rather than
        stranding it asleep on an hour nobody chose.
        """
        if self.config.wake_mode == "fixed":
            return self.config.wake_time

        menu, hours = build_alarm_menu(self.app.clock(), self.config.alarm_hours)
        result = await self.app.provider.generate(
            menu.text, schema=self.app.schemas.menu(menu.letters)
        )
        key = menu.mapping.get(str(result.get("choice", "")).strip().upper())
        if key is None:
            return self.config.wake_time
        return f"{hours[int(key)]:02d}:00"

    async def night_sleep(self) -> str:
        """Save, run quiet maintenance, sleep until wake time, wake up."""
        app = self.app
        app.status.set_activity("sleeping")
        # Asked before the save so the alarm choice is part of the day being
        # saved, and while the day is still in context for it to answer with.
        wake_at = await self.pick_wake_time()
        await app.save_now("sleep")
        if app.memory is not None:
            await app.memory.wait_idle()
            await app.memory.consolidate()
        if app.backup is not None:
            app.backup.run()

        seconds = self.seconds_until(wake_at)
        print_system(
            f"Going to sleep for the night (~{int(seconds / 3600)}h until "
            f"{format_time_12h(wake_at)})."
        )
        await app.sleep_fn(seconds)

        app.status.set_activity("waking up")
        self._defer_until = None
        wake_note = (
            f"[You just woke up. It's {app.clock().strftime('%I:%M %p')} — "
            "a brand new day.]"
        )
        notes = await app.scheduler.run_on_wake()
        return "\n".join([wake_note, *notes])

    # ~~~ naps + budget sleep ~~~
    async def nap(self, minutes: int) -> str:
        """Nap, waking early for messages or bedtime.

        Returns 'completed', 'interrupted', or a night-sleep wake-up note
        when bedtime arrives during the nap.
        """
        app = self.app
        remaining = minutes * 60
        asked = False
        while remaining > 0:
            if app.control.stop_requested:
                return "interrupted"
            chunk = min(NAP_CHECK_SECONDS, remaining)
            await app.sleep_fn(chunk)
            remaining -= chunk
            # Bedtime arrived while napping — transition to night sleep.
            if self.has_bedtime and self.in_sleep_window(app.clock()):
                print_system("Bedtime arrived during nap, going to sleep for the night.")
                return await self.night_sleep()
            # Same idea without a bedtime: a nap that ran into the night stops
            # being a nap. Waking at 10pm to pick another activity is worse
            # than just calling it a night.
            if self.config.enabled and not self.has_bedtime and self.in_night_window(app.clock()):
                print_system("The nap ran into the night, going to sleep for the night.")
                return await self.night_sleep()
            if not asked and self._unread_total() > 0:
                asked = True
                menu = build_choice_menu(
                    "[You're napping, but a message notification chimes.]",
                    options=["wake_up", "keep_sleeping"],
                    labels=["Wake up now", "Keep sleeping"],
                )
                result = await app.provider.generate(
                    menu.text, schema=app.schemas.menu(menu.letters)
                )
                if menu.mapping.get(str(result.get("choice", "")).strip().upper()) == "wake_up":
                    return "interrupted"
        return "completed"

    async def budget_sleep(self, seconds: float) -> None:
        """Forced sleep when the daily token budget is exhausted."""
        await self.app.sleep_fn(seconds)
        await self.app.scheduler.run_on_wake()

    def _unread_total(self) -> int:
        total = 0
        for channel in self.app.channels.values():
            try:
                total += channel.unread_count()
            except Exception:
                pass
        return total
