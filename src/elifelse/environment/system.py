"""The environment system: a config-driven list of places the agent can be.

The current place (plus live weather, if enabled) becomes an ambience block in
the base prompt. The environment builtin activity lets the agent move around.

The "private ambience" rule: the environment is scenery for the agent's inner
life, not a claim about the physical world — the prompt says so explicitly, so
the agent treats it as atmosphere rather than fact to assert to other people.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING

from elifelse.config import EnvironmentConfig, EnvironmentLocation
from elifelse.textutils import print_system

if TYPE_CHECKING:
    from elifelse.environment.weather import WeatherNow, WeatherService

PRIVATE_AMBIENCE_RULE = (
    "This place is your private ambience — a setting for your inner life. Let "
    "it color your mood and writing, but don't present it to others as a "
    "physical fact about where you are."
)


class EnvironmentSystem:
    def __init__(
        self,
        config: EnvironmentConfig,
        weather: WeatherService | None = None,
        clock: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.locations: dict[str, EnvironmentLocation] = {
            loc.key: loc for loc in config.locations
        }
        if not self.locations:
            raise ValueError("EnvironmentSystem needs at least one configured location")
        self.weather = weather
        self.clock = clock
        first = next(iter(self.locations))
        self.current_key = config.current if config.current in self.locations else first
        self.weather_now: WeatherNow | None = None

    @property
    def current(self) -> EnvironmentLocation:
        return self.locations[self.current_key]

    def set_current(self, key: str) -> bool:
        if key not in self.locations:
            return False
        if key != self.current_key:
            self.current_key = key
            self.weather_now = None  # different place, different sky
            print_system(f"environment: moved to {self.locations[key].name}")
        return True

    async def refresh(self) -> None:
        """Refresh the cached weather (pre-menu hook; cheap thanks to caching)."""
        if self.weather is not None:
            loc = self.current
            self.weather_now = await self.weather.current(loc.latitude, loc.longitude)

    def prompt_block(self) -> str:
        loc = self.current
        lines = [f"Where you are right now: {loc.name}. {loc.description}"]
        if self.weather_now is not None:
            lines.append(
                f"The weather here: {self.weather_now.description}, "
                f"{self.weather_now.temperature_c:.0f}C."
            )
        lines.append(PRIVATE_AMBIENCE_RULE)
        return "\n".join(lines)
