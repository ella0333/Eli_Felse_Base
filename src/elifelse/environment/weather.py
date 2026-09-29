"""Real weather for the agent's imagined location, via Open-Meteo (no API key).

Fetches are cached per coordinate and refreshed lazily; any network failure
just means no weather line — the framework never depends on it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import httpx

from elifelse.environment.wmo import describe

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

# Timezones in the United States, where a temperature reads in Fahrenheit.
# Everywhere else gets Celsius. The timezone is the one set during setup.
US_TIMEZONES = {
    "America/New_York", "America/Detroit", "America/Kentucky/Louisville",
    "America/Kentucky/Monticello", "America/Indiana/Indianapolis",
    "America/Indiana/Vincennes", "America/Indiana/Winamac", "America/Indiana/Marengo",
    "America/Indiana/Petersburg", "America/Indiana/Vevay", "America/Chicago",
    "America/Indiana/Tell_City", "America/Indiana/Knox", "America/Menominee",
    "America/North_Dakota/Center", "America/North_Dakota/New_Salem",
    "America/North_Dakota/Beulah", "America/Denver", "America/Boise", "America/Phoenix",
    "America/Los_Angeles", "America/Anchorage", "America/Juneau", "America/Sitka",
    "America/Metlakatla", "America/Yakutat", "America/Nome", "America/Adak",
    "Pacific/Honolulu", "America/Puerto_Rico",
}


def uses_fahrenheit(timezone: str) -> bool:
    return timezone in US_TIMEZONES or timezone.startswith("US/")


def format_temperature(temperature_c: float, fahrenheit: bool = False) -> str:
    """'12C', or '54F' when the person's timezone is in the US."""
    if fahrenheit:
        return f"{temperature_c * 9 / 5 + 32:.0f}F"
    return f"{temperature_c:.0f}C"


@dataclass
class WeatherNow:
    temperature_c: float
    code: int
    description: str
    fetched_at: datetime


class WeatherService:
    def __init__(
        self,
        refresh_minutes: int = 30,
        clock: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.refresh_minutes = refresh_minutes
        self._clock = clock
        self._cache: dict[tuple[float, float], WeatherNow] = {}

    async def current(self, latitude: float, longitude: float) -> WeatherNow | None:
        key = (latitude, longitude)
        cached = self._cache.get(key)
        if cached is not None:
            age = (self._clock() - cached.fetched_at).total_seconds()
            if age < self.refresh_minutes * 60:
                return cached
        fresh = await self._fetch(latitude, longitude)
        if fresh is not None:
            self._cache[key] = fresh
            return fresh
        return cached  # stale beats nothing

    async def _fetch(self, latitude: float, longitude: float) -> WeatherNow | None:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    OPEN_METEO_URL,
                    params={
                        "latitude": latitude,
                        "longitude": longitude,
                        "current": "temperature_2m,weather_code",
                        "timezone": "auto",
                    },
                )
                resp.raise_for_status()
                current = resp.json()["current"]
            code = int(current["weather_code"])
            return WeatherNow(
                temperature_c=float(current["temperature_2m"]),
                code=code,
                description=describe(code),
                fetched_at=self._clock(),
            )
        except Exception:
            return None
