"""The main loop, scripted end to end on the MockProvider: crash context every
iteration, menu enum == visible letters, note carry, graceful stop, and the
consecutive-menu-failure circuit breaker."""

import json

import pytest

from elifelse.cli import main as cli_main
from elifelse.providers.base import CompletionResult


async def test_scripted_loop_menu_activity_menu(app, mock_provider):
    """Two full iterations: menu -> journal -> menu -> ponder. Journal can't be
    picked twice running, so iteration 2 goes somewhere else."""
    await app.startup()  # discovers builtins; journal is first -> letter A
    mock_provider.feed(
        {"thinking": "let's write", "choice": "A"},
        {"thinking": "today...", "entry": "Dear diary, iteration one."},
        {"thinking": "reflective", "emotion": "calm"},  # post-journal survey
        {"thinking": "something else then", "choice": "B"},
        {"thinking": "quiet", "response": "A thought.", "return_to_menu": True},
        {"thinking": "peaceful", "emotion": "content"},  # post-ponder survey
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
    # activity — environment is hidden because its subsystem is off).
    visible = [e["key"] for e in app.registry.menu_entries()]
    menu_schema = mock_provider.calls[0]["schema"]
    assert len(menu_schema["properties"]["choice"]["enum"]) == len(visible)
    assert menu_schema["properties"]["choice"]["enum"][0] == "A"
    assert visible[0] == "journal"

    # Iteration 2 still lists journal, with the reason, but can't answer with it.
    assert "A) Write in your journal" in menu2
    assert "you just left this activity" in menu2
    assert "A" not in mock_provider.calls[3]["schema"]["properties"]["choice"]["enum"]

    # The journal entry hit disk.
    files = list(app.paths.journal.glob("*.md"))
    assert len(files) == 1
    assert "iteration one" in files[0].read_text(encoding="utf-8")

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


async def test_repeat_block_lifts_after_one_turn(app, mock_provider):
    """The block is one turn, not a ban: journal is back on the next menu."""
    await app.startup()
    mock_provider.feed(
        {"thinking": "write", "choice": "A"},
        {"thinking": "today...", "entry": "One."},
        {"thinking": "calm", "emotion": "calm"},
        {"thinking": "think instead", "choice": "B"},          # ponder
        {"thinking": "quiet", "response": "A thought.", "return_to_menu": True},
        {"thinking": "settled", "emotion": "settled"},
        {"thinking": "back to writing", "choice": "A"},        # journal again
        {"thinking": "more", "entry": "Two."},
        {"thinking": "content", "emotion": "content"},
    )
    await app.controller.main_loop(max_iterations=3)
    assert app.stats.get("activity.journal") == 2
    # Menu 3 blocks ponder (just left) and offers journal again.
    menu3 = mock_provider.calls[6]["schema"]["properties"]["choice"]["enum"]
    assert "A" in menu3 and "B" not in menu3


async def test_activity_can_exempt_itself_from_the_repeat_block(app, mock_provider):
    """allow_repeat() is read per turn, so an activity with someone waiting on
    it stays pickable back to back."""
    await app.startup()
    entries = app.registry.menu_entries()
    keys = [e["key"] for e in entries]
    assert "chat" in keys
    app.controller.last_choice_key = "chat"

    chat = app.registry.get("chat")
    ctx = app.registry.ctx_for(chat)
    assert chat.allow_repeat(ctx) is False
    blocked_key, _ = app.controller._repeat_block(entries)
    assert blocked_key == "chat"

    ctx.channels["terminal"].queue_direct("are you there?")
    assert chat.allow_repeat(ctx) is True
    assert app.controller._repeat_block(entries) == ("", "")


async def test_three_menu_failures_raise(app, mock_provider):
    await app.startup()
    # 3 menu failures x 5 validation attempts each = 15 garbage responses.
    mock_provider.feed(*["not json at all"] * 15)
    with pytest.raises(RuntimeError, match="3 times in a row"):
        await app.controller.main_loop(max_iterations=5)


async def test_a_provider_outage_holds_the_menu_instead_of_tripping_the_breaker(
    app, mock_provider, config
):
    """A rate-limited menu is the provider being away, not the model failing.
    The loop holds and asks again rather than raising after three tries."""
    config.provider.transient_retries = 0  # give up at once; the hold-off still applies
    await app.startup()
    rate_limited = CompletionResult(text=None, error="429: temporarily rate-limited upstream")
    mock_provider.feed(
        rate_limited,
        rate_limited,
        rate_limited,
        rate_limited,
        {"thinking": "at last", "choice": "A"},
        {"thinking": "today...", "entry": "It came back."},
        {"thinking": "calm", "emotion": "calm"},
    )
    await app.controller.main_loop(max_iterations=5)
    assert app.stats.get("activity.journal") == 1


async def test_a_note_survives_a_menu_the_provider_never_answered(app, mock_provider, config):
    config.provider.transient_retries = 0
    await app.startup()
    mock_provider.feed(
        CompletionResult(text=None, error="429: rate limit"),
        {"thinking": "ok", "choice": "A"},
        {"thinking": "today...", "entry": "Morning."},
        {"thinking": "calm", "emotion": "calm"},
    )
    await app.controller.main_loop(max_iterations=2, initial_note="You just woke up.")
    menu2 = mock_provider.calls[1]["messages"][-1]["content"]
    assert "You just woke up." in menu2


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
