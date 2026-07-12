"""The day cycle: bedtime, night sleep, waking up, naps, budget sleep.

At bedtime the agent gets the bedtime menu (sleep now / stay up an hour).
Night sleep is where quiet maintenance happens: save, settle background
extraction, consolidate facts, back up the data dir — then one long sleep
until wake time, then on-wake hooks and a fresh-morning note for the first menu.

Everything uses the injectable app.clock/app.sleep_fn, so tests can run a
whole "day" in milliseconds.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from elifelse.loop.menus import build_bedtime_menu
from elifelse.textutils import format_time_12h, print_system

if TYPE_CHECKING:
    from elifelse.app import App

STAY_UP_DEFER = timedelta(hours=1)
NAP_CHECK_SECONDS = 30


def _parse_hhmm(value: str) -> tuple[int, int]:
    h, m = value.split(":")
    return int(h), int(m)


class DayCycle:
    def __init__(self, app: App) -> None:
        self.app = app
        self.config = app.config.day_cycle
        self._defer_until: datetime | None = None

    def register(self) -> None:
        self.app.scheduler.add_pre_menu_hook(self.check_bedtime)

    # ~~~ time math ~~~
    def in_sleep_window(self, now: datetime) -> bool:
        bed_h, bed_m = _parse_hhmm(self.config.bedtime)
        wake_h, wake_m = _parse_hhmm(self.config.wake_time)
        t = now.hour * 60 + now.minute
        bed = bed_h * 60 + bed_m
        wake = wake_h * 60 + wake_m
        if bed == wake:
            return False
        if bed < wake:  # window inside one day (e.g. 01:00 -> 09:00)
            return bed <= t < wake
        return t >= bed or t < wake  # window crosses midnight (e.g. 22:00 -> 08:00)

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
        result = await app.provider.generate(menu, schema=app.schemas.get("bedtime_menu"))
        if result.get("choice") == "sleep":
            return await self.night_sleep()
        # stay_up (or a failed response — never force the issue on an error)
        self._defer_until = now + STAY_UP_DEFER
        return "You decided to stay up a while longer."

    async def night_sleep(self) -> str:
        """Save, run quiet maintenance, sleep until wake time, wake up."""
        app = self.app
        app.status.set_activity("sleeping")
        await app.save_now("sleep")
        if app.memory is not None:
            await app.memory.wait_idle()
            await app.memory.consolidate()
        if app.backup is not None:
            app.backup.run()

        seconds = self.seconds_until(self.config.wake_time)
        print_system(
            f"Going to sleep for the night (~{int(seconds / 3600)}h until "
            f"{format_time_12h(self.config.wake_time)})."
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
            if self.config.enabled and self.in_sleep_window(app.clock()):
                print_system("Bedtime arrived during nap, going to sleep for the night.")
                return await self.night_sleep()
            if not asked and self._unread_total() > 0:
                asked = True
                result = await app.provider.generate(
                    "[You're napping, but a message notification chimes. "
                    "Wake up now, or keep sleeping?]",
                    schema=app.schemas.get("nap_interrupted"),
                )
                if result.get("choice") == "wake_up":
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
