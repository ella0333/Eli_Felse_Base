"""Nightly backup: zip the whole data/ dir during night sleep.

One zip per calendar day, kept for KEEP_DAYS days. Locked files (e.g. an open
ChromaDB sqlite on Windows) are skipped file-by-file rather than failing the
whole backup. BackupTarget hooks let modules ship the zip somewhere (rsync,
cloud, ...) — the base only writes locally.
"""

from __future__ import annotations

import zipfile
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING

from elifelse.textutils import print_system

if TYPE_CHECKING:
    from pathlib import Path

    from elifelse.paths import Paths

BackupTarget = Callable[["Path"], None]

KEEP_DAYS = 7


class BackupSystem:
    def __init__(self, paths: Paths, clock: Callable[[], datetime] = datetime.now) -> None:
        self.paths = paths
        self.clock = clock
        self.targets: list[BackupTarget] = []

    def add_target(self, target: BackupTarget) -> None:
        """Register a hook called with the zip path after each backup."""
        self.targets.append(target)

    def run(self) -> Path | None:
        """Write today's backup zip (or skip if it already exists)."""
        zip_path = self.paths.backups / f"backup_{self.clock():%Y-%m-%d}.zip"
        if zip_path.exists():
            return None

        tmp = zip_path.with_name(zip_path.name + ".tmp")
        skipped = 0
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            for file in sorted(self.paths.data_dir.rglob("*")):
                if not file.is_file():
                    continue
                if self.paths.backups in file.parents:
                    continue  # never back up the backups
                if file.suffix == ".tmp":
                    continue
                try:
                    zf.write(file, file.relative_to(self.paths.data_dir))
                except OSError:
                    skipped += 1  # locked file (open DB etc.) — skip, don't fail
        tmp.replace(zip_path)

        note = f" ({skipped} locked files skipped)" if skipped else ""
        print_system(f"backup written: {zip_path.name}{note}")
        self._prune()

        for target in self.targets:
            try:
                target(zip_path)
            except Exception as e:  # a broken target must never break the night
                print_system(f"backup target error: {e}")
        return zip_path

    def _prune(self) -> None:
        """Keep only the newest KEEP_DAYS zips."""
        zips = sorted(self.paths.backups.glob("backup_*.zip"), reverse=True)
        for old in zips[KEEP_DAYS:]:
            try:
                old.unlink()
            except OSError:
                pass
