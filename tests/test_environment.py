"""Environment: locations, the private-ambience rule, weather caching, and the
prompt block that lands in the base prompt."""

from datetime import datetime, timedelta

import pytest

from elifelse.config import EnvironmentConfig, EnvironmentLocation
from elifelse.environment.system import PRIVATE_AMBIENCE_RULE, EnvironmentSystem
from elifelse.environment.weather import WeatherNow, WeatherService
from elifelse.environment.wmo import describe


def _config(current: str = "") -> EnvironmentConfig:
    return EnvironmentConfig(
        current=current,
        locations=[
            EnvironmentLocation(
                key="garden",
                name="The Garden",
                description="A small walled garden with a stone bench.",
                latitude=52.52,
                longitude=13.41,
            ),
            EnvironmentLocation(
                key="attic",
                name="The Attic",
                description="A dusty attic full of boxes.",
                latitude=48.85,
                longitude=2.35,
            ),
        ],
    )


class FakeTime:
    def __init__(self, start: datetime) -> None:
        self.now_dt = start

    def now(self) -> datetime:
        return self.now_dt


class FakeWeather(WeatherService):
    """Counts fetches and plays back a scripted list of results (None = failure)."""

    def __init__(self, results, clock) -> None:
        super().__init__(refresh_minutes=30, clock=clock)
        self.results = list(results)
        self.fetches = 0

    async def _fetch(self, latitude, longitude):
        self.fetches += 1
        return self.results.pop(0) if self.results else None


def _weather_now(clock, code: int = 63, temp: float = 12.3) -> WeatherNow:
    return WeatherNow(
        temperature_c=temp, code=code, description=describe(code), fetched_at=clock()
    )


# ~~~ WMO table ~~~
def test_wmo_describe():
    assert describe(0) == "clear skies"
    assert describe(95) == "a thunderstorm"
    assert describe(42) == "changeable weather"  # unknown code


# ~~~ EnvironmentSystem ~~~
def test_default_current_is_first_location():
    env = EnvironmentSystem(_config())
    assert env.current_key == "garden"
    assert env.current.name == "The Garden"


def test_configured_current_wins_and_invalid_falls_back():
    assert EnvironmentSystem(_config(current="attic")).current_key == "attic"
    assert EnvironmentSystem(_config(current="moon")).current_key == "garden"


def test_no_locations_is_a_config_error():
    with pytest.raises(ValueError, match="at least one"):
        EnvironmentSystem(EnvironmentConfig(locations=[]))


def test_prompt_block_without_weather():
    block = EnvironmentSystem(_config()).prompt_block()
    assert "The Garden" in block
    assert "stone bench" in block
    assert PRIVATE_AMBIENCE_RULE in block
    assert "The weather here" not in block


def test_set_current_switches_and_clears_weather():
    fake = FakeTime(datetime(2026, 7, 3, 12, 0))
    env = EnvironmentSystem(_config(), clock=fake.now)
    env.weather_now = _weather_now(fake.now)

    assert env.set_current("attic") is True
    assert env.current_key == "attic"
    assert env.weather_now is None  # different place, different sky

    assert env.set_current("basement") is False
    assert env.current_key == "attic"


async def test_refresh_adds_weather_line():
    fake = FakeTime(datetime(2026, 7, 3, 12, 0))
    weather = FakeWeather([_weather_now(fake.now)], clock=fake.now)
    env = EnvironmentSystem(_config(), weather=weather, clock=fake.now)

    await env.refresh()
    block = env.prompt_block()
    assert "The weather here: steady rain, 12C." in block


async def test_menu_line_without_short_is_unchanged():
    fake = FakeTime(datetime(2026, 7, 3, 12, 0))
    weather = FakeWeather([_weather_now(fake.now)] * 2, clock=fake.now)
    env = EnvironmentSystem(_config(), weather=weather, clock=fake.now)

    labels = await env._labels()
    assert labels[0] == (
        "The Garden — A small walled garden with a stone bench. [steady rain, 12C]"
    )


async def test_us_timezone_reads_fahrenheit():
    fake = FakeTime(datetime(2026, 7, 3, 12, 0))
    weather = FakeWeather([_weather_now(fake.now)], clock=fake.now)
    env = EnvironmentSystem(_config(), weather=weather, clock=fake.now, fahrenheit=True)

    await env.refresh()
    assert "The weather here: steady rain, 54F." in env.prompt_block()


def test_fahrenheit_follows_the_timezone():
    from elifelse.environment.weather import uses_fahrenheit

    assert uses_fahrenheit("America/Chicago")
    assert uses_fahrenheit("US/Eastern")
    assert not uses_fahrenheit("America/Toronto")
    assert not uses_fahrenheit("Europe/London")
    assert not uses_fahrenheit("UTC")


async def test_menu_line_with_short_keeps_the_description_for_the_prompt():
    fake = FakeTime(datetime(2026, 7, 3, 12, 0))
    config = _config(current="garden")
    config.locations[0].short = "Walled garden with a bench"
    weather = FakeWeather([_weather_now(fake.now), None], clock=fake.now)
    env = EnvironmentSystem(config, weather=weather, clock=fake.now)

    labels = await env._labels()
    assert labels[0] == "The Garden (you are here) (steady rain & cool) - Walled garden with a bench"
    assert labels[1] == "The Attic — A dusty attic full of boxes."
    assert "A small walled garden with a stone bench." in env.prompt_block()


# ~~~ WeatherService caching ~~~
async def test_weather_cached_within_ttl_and_refetched_after():
    fake = FakeTime(datetime(2026, 7, 3, 12, 0))
    weather = FakeWeather(
        [_weather_now(fake.now, code=0), _weather_now(fake.now, code=63)],
        clock=fake.now,
    )

    first = await weather.current(52.52, 13.41)
    assert first.description == "clear skies"
    assert weather.fetches == 1

    fake.now_dt += timedelta(minutes=10)
    again = await weather.current(52.52, 13.41)
    assert again is first  # cached, no new fetch
    assert weather.fetches == 1

    fake.now_dt += timedelta(minutes=25)  # 35 min old now
    fresh = await weather.current(52.52, 13.41)
    assert fresh.description == "steady rain"
    assert weather.fetches == 2


async def test_stale_weather_beats_nothing_on_failure():
    fake = FakeTime(datetime(2026, 7, 3, 12, 0))
    weather = FakeWeather([_weather_now(fake.now)], clock=fake.now)

    first = await weather.current(52.52, 13.41)
    fake.now_dt += timedelta(hours=2)
    stale = await weather.current(52.52, 13.41)  # fetch fails -> stale result
    assert stale is first
    assert weather.fetches == 2


async def test_failure_with_no_cache_is_none():
    fake = FakeTime(datetime(2026, 7, 3, 12, 0))
    weather = FakeWeather([], clock=fake.now)
    assert await weather.current(52.52, 13.41) is None


# ~~~ base prompt integration ~~~
def test_environment_block_lands_in_base_prompt(app):
    app.environment = EnvironmentSystem(_config())
    prompt = app.base_prompt()
    assert "The Garden" in prompt
    assert PRIVATE_AMBIENCE_RULE in prompt
