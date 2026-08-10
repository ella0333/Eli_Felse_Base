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
from elifelse.loop.menus import ask_menu, build_choice_menu
from elifelse.textutils import print_system

if TYPE_CHECKING:
    from elifelse.app import App
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
        # Whether the environment has actually been decided yet. current_key
        # always points somewhere so nothing downstream has to handle
        # "nowhere", but until this flips the agent has not chosen, and a
        # first run asks it. Restoring a save flips it too, so the question
        # comes up once rather than every boot.
        self.chosen = config.current in self.locations
        self.weather_now: WeatherNow | None = None

    @property
    def current(self) -> EnvironmentLocation:
        return self.locations[self.current_key]

    def set_current(self, key: str) -> bool:
        if key not in self.locations:
            return False
        self.chosen = True
        if key != self.current_key:
            self.current_key = key
            self.weather_now = None  # different place, different sky
            print_system(f"environment: moved to {self.locations[key].name}")
        return True

    async def _labels(self) -> list[str]:
        """One line per environment, carrying its live conditions where we
        have them.

        The weather for every environment is fetched up front, not just the
        current one, so the choice is made against what the skies are actually
        doing rather than against descriptions that never change.
        """
        labels = []
        for key, loc in self.locations.items():
            here = " (you are here)" if key == self.current_key and self.chosen else ""
            weather = ""
            if self.weather is not None:
                now = await self.weather.current(loc.latitude, loc.longitude)
                if now is not None:
                    weather = f" [{now.description}, {now.temperature_c:.0f}C]"
            labels.append(f"{loc.name}{here} — {loc.description}{weather}")
        return labels

    async def refresh(self) -> None:
        """Refresh the cached weather (pre-menu hook; cheap thanks to caching)."""
        if self.weather is not None:
            loc = self.current
            self.weather_now = await self.weather.current(loc.latitude, loc.longitude)

    async def select(self, app: App) -> str:
        """Put the environments to the agent and move it to whichever it picks.

        The one routine behind both callers, the first-run choice and the menu
        activity, so neither can drift from the other. Returns a note for the
        next menu.
        """
        menu = build_choice_menu(
            "Choose your environment. This is where you will exist until you "
            "change it again.",
            list(self.locations),
            labels=await self._labels(),
        )
        choice = await ask_menu(app, menu)
        if choice is None:
            # Never strand it nowhere on a bad answer: stay put, stay chosen.
            self.chosen = True
            return ""
        if choice == self.current_key and self.chosen:
            return f"You looked around, but decided to stay at {self.current.name}."
        self.set_current(choice)
        await self.refresh()  # new environment, fetch its weather
        return f"You moved to {self.current.name}."

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
