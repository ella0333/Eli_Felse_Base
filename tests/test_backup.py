"""Nightly backup: one zip per day of the whole data dir, retention, targets."""

from datetime import datetime
from zipfile import ZipFile

from elifelse.backup import KEEP_DAYS, BackupSystem
from elifelse.paths import Paths


def _paths(tmp_path) -> Paths:
    p = Paths(tmp_path / "data")
    p.ensure_tree()
    return p


def _clock():
    return datetime(2026, 7, 3, 23, 0, 0)


def test_backup_zips_data_dir(tmp_path):
    paths = _paths(tmp_path)
    (paths.journal / "2026-07-03.md").write_text("dear diary", encoding="utf-8")
    (paths.state / "stats.json").write_text("{}", encoding="utf-8")
    (paths.state / "stats.json.tmp").write_text("{}", encoding="utf-8")  # in-flight temp
    (paths.backups / "backup_2026-07-01.zip").write_bytes(b"old")

    zip_path = BackupSystem(paths, _clock).run()

    assert zip_path is not None and zip_path.name == "backup_2026-07-03.zip"
    with ZipFile(zip_path) as zf:
        names = zf.namelist()
    assert "journal/2026-07-03.md" in names
    assert "state/stats.json" in names
    assert not any(n.endswith(".tmp") for n in names)  # temp files skipped
    assert not any(n.startswith("backups") for n in names)  # never zip the zips


def test_backup_once_per_day(tmp_path):
    paths = _paths(tmp_path)
    (paths.journal / "a.md").write_text("x", encoding="utf-8")
    backup = BackupSystem(paths, _clock)
    assert backup.run() is not None
    assert backup.run() is None  # today's zip already exists


def test_backup_retention_keeps_newest(tmp_path):
    paths = _paths(tmp_path)
    for day in range(10, 20):
        (paths.backups / f"backup_2026-06-{day}.zip").write_bytes(b"old")

    BackupSystem(paths, _clock).run()

    zips = sorted(p.name for p in paths.backups.glob("backup_*.zip"))
    assert len(zips) == KEEP_DAYS
    assert zips[-1] == "backup_2026-07-03.zip"  # newest survived
    assert "backup_2026-06-10.zip" not in zips  # oldest pruned


def test_backup_targets_get_the_zip(tmp_path):
    paths = _paths(tmp_path)
    backup = BackupSystem(paths, _clock)
    got = []
    backup.add_target(got.append)

    def broken(path):
        raise RuntimeError("target down")

    backup.add_target(broken)  # a broken target must not break the backup

    zip_path = backup.run()
    assert got == [zip_path]
