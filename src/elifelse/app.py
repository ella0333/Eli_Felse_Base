"""The App object — explicit ownership of every subsystem.

This replaces the classic "module full of globals" pattern: everything the
framework needs hangs off one typed object, wired in __init__ in dependency
order. Tests build as many independent Apps as they like; modules never see
this object (they get an ActivityContext).

Subsystems that land in later phases (memory, summaries, inner life,
environment, day cycle, saves) are Optional[...] = None seams: every caller
already None-guards them, so each phase slots in without touching the loop.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from elifelse.activities.registry import ActivityRegistry
from elifelse.config import Config
from elifelse.logging_setup import setup_logging
from elifelse.loop.control import ControlState
from elifelse.loop.controller import Controller
from elifelse.loop.scheduler import Scheduler
from elifelse.paths import Paths
from elifelse.persona import Persona
from elifelse.providers import Provider, create_provider
from elifelse.structured.registry import SchemaRegistry
from elifelse.trackers.activity import ActivityTracker
from elifelse.trackers.limits import DailyLimits
from elifelse.trackers.stats import StatsTracker
from elifelse.trackers.status import StatusTracker, terminal_sink


class App:
    def __init__(
        self,
        config: Config,
        persona: Persona,
        provider: Provider | None = None,
        clock: Callable[[], datetime] = datetime.now,
        sleep_fn: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.config = config
        self.persona = persona
        self.clock = clock
        self.sleep_fn = sleep_fn

        self.paths = Paths(config.data_dir)
        self.paths.ensure_tree()
        self.logger = setup_logging(self.paths.logs, config.logging.level)

        # ~~~ model access ~~~
        self.schemas = SchemaRegistry()
        self.provider: Provider = provider if provider is not None else create_provider(config)
        self.provider.agent_name = persona.name

        # ~~~ trackers ~~~
        self.activity_tracker = ActivityTracker(clock)
        self.status = StatusTracker(clock)
        self.status.add_sink(terminal_sink)
        self.stats = StatsTracker(self.paths.stats, clock)
        self.limits = DailyLimits(self.paths.limits, clock)

        # ~~~ loop machinery ~~~
        self.channels: dict[str, Any] = {}
        self.control = ControlState()
        self.scheduler = Scheduler()
        self.registry = ActivityRegistry(self)
        self.controller = Controller(self)

        # ~~~ later-phase subsystems (None = feature off / not yet wired) ~~~
        self.memory: Any | None = None
        self.summaries: Any | None = None
        self.innerlife: Any | None = None
        self.environment: Any | None = None
        self.daycycle: Any | None = None
        self.saves: Any | None = None
        self.backup: Any | None = None
        self._ws_sink: Any | None = None
        self._dashboard: Any | None = None

    # ~~~ prompt / status ~~~
    def base_prompt(self) -> str:
        from elifelse.prompts import build_base_prompt

        return build_base_prompt(self)

    def notification_line(self) -> str:
        """One line summarizing unread messages across all channels ('' = none)."""
        parts = []
        for name, channel in self.channels.items():
            try:
                unread = channel.unread_count()
            except Exception:
                unread = 0
            if unread:
                parts.append(f"{unread} unread ({name})")
        if not parts:
            return ""
        return "You have messages waiting: " + ", ".join(parts)

    # ~~~ lifecycle ~~~
    async def startup(self, discover: bool = True) -> None:
        """Boot: load the model, discover activities, run their startups."""
        await self.provider.ensure_loaded()
        self._init_memory()
        self._init_subsystems()
        if self.config.status.websocket_enabled and self._ws_sink is None:
            from elifelse.trackers.ws_sink import WebSocketSink

            self._ws_sink = WebSocketSink(self.config.status.websocket_port)
            await self._ws_sink.start()
            self.status.add_sink(self._ws_sink)
        # Dashboard is launched on demand via /dashboard command (not auto-started).
        if discover:
            self.registry.discover_all()
        await self.registry.run_startups()
        self.stats.session_started()
        self.provider.set_system_prompt(self.base_prompt())
        self.logger.info("startup complete (%d activities)", len(self.registry.activities))

    def _init_memory(self) -> None:
        """Wire memory + summaries (skipped when disabled or pre-injected by tests)."""
        if not self.config.memory.enabled or self.memory is not None:
            return
        from elifelse.memory.chroma import ChromaStore
        from elifelse.memory.system import MemorySystem
        from elifelse.summary.system import SummarySystem

        store = ChromaStore(self.paths.chromadb)
        self.memory = MemorySystem(self.provider, store, self.config.memory,
                                   self.schemas, self.clock)
        self.summaries = SummarySystem(self.provider, store, self.config.summary,
                                       self.persona.name, self.config.developer_name, self.clock)

    def _init_subsystems(self) -> None:
        """Inner life, environment, day cycle — each behind its own toggle."""
        if self.config.inner_life.enabled and self.innerlife is None:
            from elifelse.innerlife.system import InnerLife

            self.innerlife = InnerLife(self.provider, self.schemas, self.paths, self.clock)

        if (
            self.config.environment.enabled
            and self.config.environment.locations
            and self.environment is None
        ):
            from elifelse.environment.system import EnvironmentSystem
            from elifelse.environment.weather import WeatherService

            weather = WeatherService(clock=self.clock) if self.config.environment.weather else None
            self.environment = EnvironmentSystem(self.config.environment, weather, self.clock)
            self.scheduler.add_pre_menu_hook(self._environment_refresh)

        if self.config.day_cycle.enabled and self.daycycle is None:
            from elifelse.loop.daycycle import DayCycle

            self.daycycle = DayCycle(self)
            self.daycycle.register()

        if self.saves is None:
            from elifelse.state.saves import SaveSystem

            self.saves = SaveSystem(self)

        if self.config.backup.enabled and self.backup is None:
            from elifelse.backup import BackupSystem

            self.backup = BackupSystem(self.paths, self.clock)

    async def _environment_refresh(self) -> None:
        if self.environment is not None:
            await self.environment.refresh()

    async def run(self, max_iterations: int | None = None, initial_note: str = "") -> None:
        await self.controller.main_loop(max_iterations, initial_note)

    async def save_now(self, reason: str) -> None:
        """Persist a save if the save system is wired (Phase 7); else a no-op."""
        if self.saves is not None:
            await self.saves.save(reason)

    async def shutdown(self) -> None:
        if self.memory is not None:
            await self.memory.wait_idle()
        if self._dashboard is not None:
            self._dashboard.stop()
        if self._ws_sink is not None:
            await self._ws_sink.stop()
        close = getattr(self.provider, "close", None)
        if close is not None:
            await close()
        self.logger.info("shutdown complete")
