"""The day cycle on a fully fake clock: sleep windows, bedtime menu, night
sleep, stay-up deferral, and naps — a whole 'day' runs in milliseconds."""

from datetime import datetime, timedelta

import pytest

from elifelse.app import App
from elifelse.loop.daycycle import DayCycle
from elifelse.providers.mock import MockProvider


class FakeTime:
    """Injectable clock + sleep: sleeping advances the clock instantly."""

    def __init__(self, start: datetime) -> None:
        self.now_dt = start
        self.sleeps: list[float] = []

    def now(self) -> datetime:
        return self.now_dt

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now_dt += timedelta(seconds=seconds)


@pytest.fixture
def fake():
    return FakeTime(datetime(2026, 7, 3, 12, 0))


@pytest.fixture
def dapp(config, persona, fake):
    """App on the old fixed schedule: 22:00 bedtime, always wakes at 08:00.

    Not the defaults any more, but it is the arrangement most of these tests
    are about. The no-bedtime and alarm paths set their own.
    """
    config.day_cycle.enabled = True
    config.day_cycle.bedtime = "22:00"
    config.day_cycle.wake_mode = "fixed"
    provider = MockProvider(config)
    return App(config, persona, provider=provider, clock=fake.now, sleep_fn=fake.sleep)


# ~~~ time math ~~~
def test_in_sleep_window_crossing_midnight(dapp):
    dc = DayCycle(dapp)  # 22:00 -> 08:00 defaults
    day = datetime(2026, 7, 3, 0, 0)
    assert dc.in_sleep_window(day.replace(hour=23)) is True
    assert dc.in_sleep_window(day.replace(hour=3)) is True
    assert dc.in_sleep_window(day.replace(hour=22)) is True  # bed boundary in
    assert dc.in_sleep_window(day.replace(hour=8)) is False  # wake boundary out
    assert dc.in_sleep_window(day.replace(hour=12)) is False


def test_in_sleep_window_same_day_and_degenerate(dapp):
    dc = DayCycle(dapp)
    dc.config.bedtime = "01:00"
    dc.config.wake_time = "09:00"
    day = datetime(2026, 7, 3, 0, 0)
    assert dc.in_sleep_window(day.replace(hour=2)) is True
    assert dc.in_sleep_window(day.replace(minute=30)) is False  # 00:30
    assert dc.in_sleep_window(day.replace(hour=10)) is False

    dc.config.wake_time = "01:00"  # bed == wake -> never sleeps
    assert dc.in_sleep_window(day.replace(hour=1)) is False


def test_no_bedtime_is_never_a_sleep_window(dapp):
    """The default. Nothing is scheduled, so no hour is ever "time for bed"."""
    dc = DayCycle(dapp)
    dc.config.bedtime = ""
    day = datetime(2026, 7, 3, 0, 0)
    assert dc.in_sleep_window(day.replace(hour=23)) is False
    assert dc.in_sleep_window(day.replace(hour=3)) is False
    assert dc.has_bedtime is False


def test_night_window_ends_at_the_earliest_alarm(dapp):
    """In alarm mode the night runs until the first hour it could have set."""
    dc = DayCycle(dapp)
    dc.config.bedtime = ""
    dc.config.wake_mode = "alarm"  # alarm_hours 4..11 -> night ends at 04:00
    day = datetime(2026, 7, 3, 0, 0)
    assert dc.night_ends_at() == "04:00"
    assert dc.in_night_window(day.replace(hour=21)) is True   # night_start
    assert dc.in_night_window(day.replace(hour=2)) is True
    assert dc.in_night_window(day.replace(hour=4)) is False
    assert dc.in_night_window(day.replace(hour=20, minute=59)) is False


def test_night_window_ends_at_wake_time_when_fixed(dapp):
    dc = DayCycle(dapp)  # fixed mode, 08:00
    day = datetime(2026, 7, 3, 0, 0)
    assert dc.night_ends_at() == "08:00"
    assert dc.in_night_window(day.replace(hour=6)) is True
    assert dc.in_night_window(day.replace(hour=8)) is False


def test_seconds_until(dapp):
    dc = DayCycle(dapp)  # fake clock at 12:00
    assert dc.seconds_until("22:00") == 10 * 3600
    assert dc.seconds_until("08:00") == 20 * 3600  # tomorrow morning


# ~~~ bedtime ~~~
async def test_no_bedtime_outside_window(dapp):
    dc = DayCycle(dapp)
    dc._defer_until = datetime(2026, 7, 3, 23, 0)  # stale deferral
    assert await dc.check_bedtime() is None  # 12:00 -> not bedtime
    assert dapp.provider.calls == []
    assert dc._defer_until is None  # leaving the window resets deferral


async def test_bedtime_sleep_flow(dapp, fake):
    fake.now_dt = datetime(2026, 7, 3, 22, 30)
    dc = DayCycle(dapp)
    dapp.provider.feed({"thinking": "sleepy", "choice": "A"})

    async def morning_hook():
        return "The garden is dewy."

    dapp.scheduler.add_on_wake_hook(morning_hook)

    note = await dc.check_bedtime()

    assert fake.sleeps[-1] == 9.5 * 3600  # 22:30 -> 08:00
    assert "You just woke up" in note
    assert "08:00 AM" in note
    assert "The garden is dewy." in note
    assert dapp.status.activity == "waking up"
    # The bedtime menu is lettered like every other menu: the enum is the
    # letters, and the option text only ever appears in the prompt.
    schema = dapp.provider.calls[0]["schema"]
    assert schema["properties"]["choice"]["enum"] == ["A", "B"]
    menu_text = str(dapp.provider.calls[0]["messages"])
    assert "A) Go to sleep for the night" in menu_text
    assert "B) Stay up a while longer" in menu_text
    # Bedtime is displayed in 12h format.
    assert "10:00 PM" in menu_text


async def test_stay_up_defers_an_hour(dapp, fake):
    fake.now_dt = datetime(2026, 7, 3, 22, 30)
    dc = DayCycle(dapp)
    dapp.provider.feed({"thinking": "not yet", "choice": "B"})  # B = stay up

    note = await dc.check_bedtime()
    assert note == "You decided to stay up a while longer."
    assert fake.sleeps == []

    fake.now_dt += timedelta(minutes=30)  # 23:00, still deferred
    assert await dc.check_bedtime() is None
    assert len(dapp.provider.calls) == 1  # no second ask

    fake.now_dt += timedelta(minutes=40)  # 23:40, deferral expired
    dapp.provider.feed({"thinking": "ok ok", "choice": "A"})
    note = await dc.check_bedtime()
    assert "You just woke up" in note


async def test_failed_bedtime_answer_never_forces_sleep(dapp, fake):
    fake.now_dt = datetime(2026, 7, 3, 22, 30)
    dc = DayCycle(dapp)
    dapp.provider.feed(*["garbage"] * 5)  # exhausts the validation loop

    note = await dc.check_bedtime()
    assert note == "You decided to stay up a while longer."
    assert fake.sleeps == []  # never slept on an error


# ~~~ waking up ~~~
async def test_alarm_menu_sets_the_wake_hour(dapp, fake):
    """It picks its own wake time, and the night runs exactly that long."""
    fake.now_dt = datetime(2026, 7, 3, 22, 0)
    dapp.config.day_cycle.bedtime = ""
    dapp.config.day_cycle.wake_mode = "alarm"
    dc = DayCycle(dapp)
    dapp.provider.feed({"thinking": "a long one", "choice": "C"})  # 4,5,6 -> 06:00

    note = await dc.night_sleep()
    assert fake.sleeps[-1] == 8 * 3600  # 22:00 -> 06:00
    assert "You just woke up" in note

    menu_text = str(dapp.provider.calls[0]["messages"])
    assert "A) 4:00 AM (6 hours of sleep)" in menu_text
    assert "C) 6:00 AM (8 hours of sleep)" in menu_text
    assert "H) 11:00 AM (13 hours of sleep)" in menu_text
    # Every hour is offered; there is no cap on how long it may sleep.
    assert dapp.provider.calls[0]["schema"]["properties"]["choice"]["enum"] == list("ABCDEFGH")


async def test_alarm_answer_that_fails_falls_back_to_wake_time(dapp, fake):
    fake.now_dt = datetime(2026, 7, 3, 22, 0)
    dapp.config.day_cycle.wake_mode = "alarm"
    dc = DayCycle(dapp)
    dapp.provider.feed(*["garbage"] * 5)  # exhausts the validation loop

    await dc.night_sleep()
    assert fake.sleeps[-1] == 10 * 3600  # 22:00 -> 08:00, the configured fallback


async def test_fixed_mode_never_asks(dapp, fake):
    fake.now_dt = datetime(2026, 7, 3, 22, 0)
    dc = DayCycle(dapp)  # fixed mode
    await dc.night_sleep()
    assert fake.sleeps[-1] == 10 * 3600
    assert dapp.provider.calls == []  # nothing to choose, so nothing is asked


# ~~~ naps ~~~
async def test_nap_completes_in_chunks(dapp, fake):
    dc = DayCycle(dapp)
    assert await dc.nap(1) == "completed"
    assert fake.sleeps == [30, 30]
    assert dapp.provider.calls == []  # no messages, never asked


async def test_nap_interrupted_by_message(dapp, fake):
    class NoisyChannel:
        def unread_count(self):
            return 1

    dapp.channels["terminal"] = NoisyChannel()
    dc = DayCycle(dapp)
    dapp.provider.feed({"thinking": "who's that?", "choice": "A"})  # wake up now

    assert await dc.nap(10) == "interrupted"
    assert len(fake.sleeps) == 1  # woke after the first chunk


async def test_nap_keeps_sleeping_asks_only_once(dapp, fake):
    class NoisyChannel:
        def unread_count(self):
            return 1

    dapp.channels["terminal"] = NoisyChannel()
    dc = DayCycle(dapp)
    dapp.provider.feed({"thinking": "later", "choice": "B"})  # keep sleeping

    assert await dc.nap(2) == "completed"
    assert len(fake.sleeps) == 4  # all four 30s chunks
    naps_asked = [c for c in dapp.provider.calls if "notification chimes" in str(c["messages"])]
    assert len(naps_asked) == 1  # once asked, the answer stands


async def test_nap_that_runs_into_the_night_becomes_the_night(dapp, fake):
    """No bedtime to collide with, but a nap ending at 9pm still ends the day."""
    fake.now_dt = datetime(2026, 7, 3, 20, 59, 30)
    dapp.config.day_cycle.bedtime = ""
    dc = DayCycle(dapp)  # fixed mode, so no alarm menu in the way

    note = await dc.nap(10)
    assert "You just woke up" in note  # the night's wake note, not "completed"
    assert fake.sleeps[-1] == 11 * 3600  # 21:00 -> 08:00


async def test_nap_interrupted_by_stop_request(dapp, fake):
    dc = DayCycle(dapp)
    dapp.control.request_stop()
    assert await dc.nap(10) == "interrupted"
    assert fake.sleeps == []


async def test_budget_sleep_runs_wake_hooks(dapp, fake):
    ran = []

    async def hook():
        ran.append(True)
        return None

    dapp.scheduler.add_on_wake_hook(hook)
    dc = DayCycle(dapp)
    await dc.budget_sleep(120)
    assert fake.sleeps == [120]
    assert ran == [True]


# ~~~ wiring ~~~
async def test_startup_registers_daycycle(dapp):
    await dapp.startup(discover=False)
    assert dapp.daycycle is not None
    assert dapp.daycycle.check_bedtime in dapp.scheduler.pre_menu_hooks


async def test_daycycle_built_but_unhooked_when_disabled(dapp):
    """Disabled means it never sleeps, not no day cycle. Naps need the object."""
    dapp.config.day_cycle.enabled = False
    await dapp.startup(discover=False)
    assert dapp.daycycle is not None
    assert dapp.daycycle.check_bedtime not in dapp.scheduler.pre_menu_hooks


async def test_no_bedtime_wires_no_hook(dapp):
    """Sleeping with no bedtime is the default, and nothing interrupts the menu."""
    dapp.config.day_cycle.bedtime = ""
    await dapp.startup(discover=False)
    assert dapp.daycycle is not None
    assert dapp.daycycle.check_bedtime not in dapp.scheduler.pre_menu_hooks


# ~~~ minutes_until_bedtime ~~~
def test_minutes_until_bedtime(dapp, fake):
    dc = DayCycle(dapp)  # 22:00 -> 08:00 defaults, clock at 12:00
    assert dc.minutes_until_bedtime() == 10 * 60
    fake.now_dt = datetime(2026, 7, 3, 21, 30)
    assert dc.minutes_until_bedtime() == 30
    fake.now_dt = datetime(2026, 7, 3, 23, 0)  # already in the sleep window
    assert dc.minutes_until_bedtime() == 0
