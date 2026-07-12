"""Named saves + startup selection.

A save/load roundtrip must restore the context byte-identically; startup
priority is --load > --fresh > leftover crash context > clean start.
"""

from datetime import datetime, timedelta

import pytest

from elifelse.app import App
from elifelse.cli import main as cli_main
from elifelse.config import ConfigError
from elifelse.providers.mock import MockProvider
from elifelse.state.crash import write_crash_context
from elifelse.state.startup import select_startup


class FakeClock:
    def __init__(self, start: datetime) -> None:
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)


def _fill_context(app):
    ctx = app.provider.context
    ctx.messages.append({"role": "user", "content": "remember me"})
    ctx.timestamps.append("2026-07-03T12:00:00")
    return (list(ctx.messages), list(ctx.timestamps), ctx.system_prompt)


async def test_save_load_roundtrip_restores_context(app):
    await app.startup(discover=False)
    before = _fill_context(app)

    path = await app.saves.save("stop", name="milestone")
    assert path.exists()

    # Wipe the live context, then load the save back.
    app.provider.context.messages.clear()
    app.provider.context.timestamps.clear()
    note = app.saves.load("milestone")

    ctx = app.provider.context
    assert (list(ctx.messages), list(ctx.timestamps), ctx.system_prompt) == before
    assert "milestone" in note


async def test_list_saves_newest_first(config, persona):
    fake = FakeClock(datetime(2026, 7, 3, 12, 0, 0))
    app = App(config, persona, provider=MockProvider(config), clock=fake.now)
    await app.startup(discover=False)

    await app.saves.save("sleep")
    fake.advance(60)
    await app.saves.save("pause", name="Nap Time!")
    # A corrupt file in the saves dir is skipped, not fatal.
    (app.paths.saves / "junk.json").write_text("{not json", encoding="utf-8")

    entries = app.saves.list_saves()
    assert [e["name"] for e in entries] == ["Nap Time!", "sleep"]
    assert entries[0]["file"].endswith("_nap_time.json")  # sanitized label
    assert entries[1]["reason"] == "sleep"


async def test_load_unknown_name_lists_available(app):
    await app.startup(discover=False)
    await app.saves.save("sleep", name="alpha")
    with pytest.raises(ConfigError, match="No save named 'beta'.*alpha"):
        app.saves.load("beta")


async def test_startup_load_beats_everything(app):
    await app.startup(discover=False)
    before = _fill_context(app)
    await app.saves.save("stop", name="milestone")
    write_crash_context(app, "crash note")

    app.provider.context.messages.clear()
    app.provider.context.timestamps.clear()
    note = select_startup(app, fresh=True, load="milestone")

    assert "milestone" in note
    assert list(app.provider.context.messages) == before[0]


async def test_startup_fresh_clears_crash_context(app):
    await app.startup(discover=False)
    write_crash_context(app, "leftover")
    assert app.paths.crash_context.exists()

    note = select_startup(app, fresh=True)
    assert note == ""
    assert not app.paths.crash_context.exists()


async def test_startup_crash_context_auto_resumes(app):
    await app.startup(discover=False)
    before = _fill_context(app)
    write_crash_context(app, "mid-journal")

    app.provider.context.messages.clear()
    note = select_startup(app)

    assert "restarted unexpectedly" in note
    assert list(app.provider.context.messages) == before[0]


async def test_startup_clean_start_is_silent(app):
    await app.startup(discover=False)
    assert select_startup(app) == ""


async def test_graceful_pause_saves_then_resumes(app, mock_provider):
    """/pause path: the loop saves with reason 'pause', idles, then resumes."""
    import asyncio

    await app.startup()
    mock_provider.feed(
        {"thinking": "x", "choice": "A"},
        {"thinking": "y", "entry": "post-pause entry"},
    )
    app.control.request_pause()
    asyncio.get_running_loop().call_later(0.05, app.control.resume)

    await app.controller.main_loop(max_iterations=2)  # iter1 = pause, iter2 = journal

    assert any(s["reason"] == "pause" for s in app.saves.list_saves())
    assert app.stats.get("activity.journal") == 1


def test_cli_saves_command_empty(tmp_path, capsys):
    code = cli_main(
        ["saves", "--config", str(tmp_path / "nope.yaml"), "--data-dir", str(tmp_path / "data")]
    )
    assert code == 0
    assert "no saves yet" in capsys.readouterr().out
