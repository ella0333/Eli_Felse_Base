"""The main loop, scripted end to end on the MockProvider: crash context every
iteration, menu enum == visible letters, note carry, graceful stop, and the
consecutive-menu-failure circuit breaker."""

import json

import pytest

from elifelse.cli import main as cli_main


async def test_scripted_loop_menu_activity_menu(app, mock_provider):
    """Two full iterations: menu -> journal -> menu -> journal."""
    await app.startup()  # discovers builtins; journal is first -> letter A
    mock_provider.feed(
        {"thinking": "let's write", "choice": "A"},
        {"thinking": "today...", "entry": "Dear diary, iteration one."},
        {"thinking": "reflective", "emotion": "calm"},  # post-journal survey
        {"thinking": "again", "choice": "A"},
        {"thinking": "more", "entry": "Dear diary, iteration two."},
        {"thinking": "peaceful", "emotion": "content"},  # post-journal survey
    )

    # Crash context must exist at every iteration (written before the menu).
    seen = []

    async def crash_check():
        assert app.paths.crash_context.exists()
        data = json.loads(app.paths.crash_context.read_text(encoding="utf-8"))
        seen.append(data["note"])
        return None

    app.scheduler.add_pre_menu_hook(crash_check)

    await app.controller.main_loop(max_iterations=2)

    # Ran both iterations, crash context checked in each.
    assert len(seen) == 2
    # The activity note was saved into iteration 2's crash context...
    assert seen[1] == "You just finished writing in your journal."
    # ...and shown at the top of iteration 2's menu.
    # calls: [0] menu, [1] journal, [2] survey, [3] menu2, [4] journal2, [5] survey2
    menu2 = mock_provider.calls[3]["messages"][-1]["content"]
    assert "You just finished writing in your journal." in menu2

    # The menu schema's enum is exactly the visible letters (one per available
    # activity — nap/environment are hidden because their subsystems are off).
    visible = [e["key"] for e in app.registry.menu_entries()]
    menu_schema = mock_provider.calls[0]["schema"]
    assert len(menu_schema["properties"]["choice"]["enum"]) == len(visible)
    assert menu_schema["properties"]["choice"]["enum"][0] == "A"
    assert visible[0] == "journal"

    # Both journal entries hit disk.
    files = list(app.paths.journal.glob("*.md"))
    assert len(files) == 1
    text = files[0].read_text(encoding="utf-8")
    assert "iteration one" in text and "iteration two" in text

    # Clean end (iteration budget) clears the crash context.
    assert not app.paths.crash_context.exists()


async def test_out_of_enum_choice_never_dispatches(app, mock_provider):
    """An invalid menu answer is retried and only a real letter dispatches."""
    await app.startup()
    mock_provider.feed(
        {"thinking": "hmm", "choice": "Z"},  # not on the menu -> rejected
        {"thinking": "ok", "choice": "A"},
        {"thinking": "write", "entry": "Made it."},
        {"thinking": "ok", "emotion": "relieved"},  # post-journal survey
    )
    await app.controller.main_loop(max_iterations=1)
    assert app.stats.get("activity.journal") == 1


async def test_three_menu_failures_raise(app, mock_provider):
    await app.startup()
    # 3 menu failures x 5 validation attempts each = 15 garbage responses.
    mock_provider.feed(*["not json at all"] * 15)
    with pytest.raises(RuntimeError, match="3 times in a row"):
        await app.controller.main_loop(max_iterations=5)


async def test_stop_request_exits_cleanly(app):
    await app.startup()
    app.control.request_stop()
    await app.controller.main_loop(max_iterations=10)
    assert app.status.activity == "stopped"
    assert not app.paths.crash_context.exists()


def test_cli_end_to_end_mock(tmp_path):
    """The one-command e2e: mock provider, exit 0. Memory is disabled here so
    CI never touches ChromaDB's embedder (which downloads a model on first
    use); the real-ChromaDB e2e is the manual `elifelse run --provider mock`
    smoke check."""
    config = tmp_path / "config.yaml"
    # Memory off (Chroma's embedder downloads a model on first use); day cycle
    # off (a CI run at 23:00 would otherwise sleep until morning).
    config.write_text(
        "memory:\n  enabled: false\nday_cycle:\n  enabled: false\n", encoding="utf-8"
    )
    code = cli_main(
        [
            "run",
            "--provider", "mock",
            "--data-dir", str(tmp_path / "data"),
            "--max-iterations", "2",
            "--config", str(config),
            "--persona", str(tmp_path / "persona.yaml"),    # doesn't exist -> built-in
        ]
    )
    assert code == 0
    # It really ran: journal entries were written.
    journal = tmp_path / "data" / "journal"
    assert any(journal.glob("*.md"))
