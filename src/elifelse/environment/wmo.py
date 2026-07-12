"""WMO weather code -> short sensory description (for the prompt, not a report)."""

from __future__ import annotations

WMO_DESCRIPTIONS: dict[int, str] = {
    0: "clear skies",
    1: "mostly clear skies",
    2: "partly cloudy",
    3: "overcast",
    45: "fog hanging in the air",
    48: "freezing fog",
    51: "a light drizzle",
    53: "drizzle",
    55: "heavy drizzle",
    56: "freezing drizzle",
    57: "heavy freezing drizzle",
    61: "light rain",
    63: "steady rain",
    65: "heavy rain",
    66: "freezing rain",
    67: "heavy freezing rain",
    71: "light snowfall",
    73: "steady snowfall",
    75: "heavy snowfall",
    77: "snow grains drifting down",
    80: "light rain showers",
    81: "rain showers",
    82: "violent rain showers",
    85: "light snow showers",
    86: "heavy snow showers",
    95: "a thunderstorm",
    96: "a thunderstorm with light hail",
    99: "a thunderstorm with heavy hail",
}


def describe(code: int) -> str:
    return WMO_DESCRIPTIONS.get(code, "changeable weather")
