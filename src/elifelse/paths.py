"""Everything the agent stores lives under one configurable data directory.

No hardcoded drive paths anywhere in the framework — this module is the single
place directory layout is defined.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Paths:
    data_dir: Path

    logs: Path = field(init=False)
    chromadb: Path = field(init=False)
    journal: Path = field(init=False)
    profiles: Path = field(init=False)
    saves: Path = field(init=False)
    modules: Path = field(init=False)
    backups: Path = field(init=False)
    surveys: Path = field(init=False)
    activities: Path = field(init=False)
    state: Path = field(init=False)

    def __post_init__(self) -> None:
        self.data_dir = Path(self.data_dir).expanduser().resolve()
        self.logs = self.data_dir / "logs"
        self.chromadb = self.data_dir / "chromadb"
        self.journal = self.data_dir / "journal"
        self.profiles = self.data_dir / "profiles"
        self.saves = self.data_dir / "saves"
        self.modules = self.data_dir / "modules"
        self.backups = self.data_dir / "backups"
        self.surveys = self.data_dir / "surveys"
        self.activities = self.data_dir / "activities"
        self.state = self.data_dir / "state"

    def ensure_tree(self) -> None:
        for p in (
            self.data_dir, self.logs, self.chromadb, self.journal, self.profiles,
            self.saves, self.modules, self.backups, self.surveys, self.activities,
            self.state,
        ):
            p.mkdir(parents=True, exist_ok=True)

    def activity_dir(self, key: str) -> Path:
        """Per-activity storage folder (created on demand)."""
        d = self.activities / key
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def crash_context(self) -> Path:
        return self.state / "crash_context.json"

    @property
    def stats(self) -> Path:
        return self.state / "lifetime_stats.json"

    @property
    def limits(self) -> Path:
        return self.state / "daily_limits.json"
