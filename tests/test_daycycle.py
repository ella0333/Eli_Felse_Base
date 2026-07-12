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
    """App with the day cycle enabled and time fully faked."""
    config.day_cycle.enabled = True
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
    dapp.provider.feed({"thinking": "sleepy", "choice": "sleep"})

    async def morning_hook():
        return "The garden is dewy."

    dapp.scheduler.add_on_wake_hook(morning_hook)

    note = await dc.check_bedtime()

    assert fake.sleeps[-1] == 9.5 * 3600  # 22:30 -> 08:00
    assert "You just woke up" in note
    assert "08:00 AM" in note
    assert "The garden is dewy." in note
    assert dapp.status.activity == "waking up"
    # The bedtime menu used the schema-constrained enum.
    schema = dapp.provider.calls[0]["schema"]
    assert schema["properties"]["choice"]["enum"] == ["sleep", "stay_up"]
    # Bedtime is displayed in 12h format.
    menu_text = str(dapp.provider.calls[0]["messages"])
    assert "10:00 PM" in menu_text


async def test_stay_up_defers_an_hour(dapp, fake):
    fake.now_dt = datetime(2026, 7, 3, 22, 30)
    dc = DayCycle(dapp)
    dapp.provider.feed({"thinking": "not yet", "choice": "stay_up"})

    note = await dc.check_bedtime()
    assert note == "You decided to stay up a while longer."
    assert fake.sleeps == []

    fake.now_dt += timedelta(minutes=30)  # 23:00, still deferred
    assert await dc.check_bedtime() is None
    assert len(dapp.provider.calls) == 1  # no second ask

    fake.now_dt += timedelta(minutes=40)  # 23:40, deferral expired
    dapp.provider.feed({"thinking": "ok ok", "choice": "sleep"})
    note = await dc.check_bedtime()
    assert "You just woke up" in note


async def test_failed_bedtime_answer_never_forces_sleep(dapp, fake):
    fake.now_dt = datetime(2026, 7, 3, 22, 30)
    dc = DayCycle(dapp)
    dapp.provider.feed(*["garbage"] * 5)  # exhausts the validation loop

    note = await dc.check_bedtime()
    assert note == "You decided to stay up a while longer."
    assert fake.sleeps == []  # never slept on an error


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
    dapp.provider.feed({"thinking": "who's that?", "choice": "wake_up"})

    assert await dc.nap(10) == "interrupted"
    assert len(fake.sleeps) == 1  # woke after the first chunk


async def test_nap_keeps_sleeping_asks_only_once(dapp, fake):
    class NoisyChannel:
        def unread_count(self):
            return 1

    dapp.channels["terminal"] = NoisyChannel()
    dc = DayCycle(dapp)
    dapp.provider.feed({"thinking": "later", "choice": "keep_sleeping"})

    assert await dc.nap(2) == "completed"
    assert len(fake.sleeps) == 4  # all four 30s chunks
    naps_asked = [c for c in dapp.provider.calls if "wake_up" in str(c["schema"])]
    assert len(naps_asked) == 1  # once asked, the answer stands


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
