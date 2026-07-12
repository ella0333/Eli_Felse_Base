"""The shared activity lifecycle: snapshots, isolation, the compact injection,
tracker records, and the GenerationError safety net."""

from elifelse.activities.base import Activity
from elifelse.loop.lifecycle import run_activity
from elifelse.providers.base import GenerationError


class TalkerActivity(Activity):
    """Adds one exchange to the context via the safe ctx surface."""

    key = "talker"
    menu_label = "Talk"

    async def run(self, ctx):
        await ctx.freetext("Say something.")
        return "done talking"


class IsolatedActivity(TalkerActivity):
    key = "isolated"
    menu_label = "Isolated Game"
    isolate_context = True


class FailingActivity(Activity):
    key = "failing"
    menu_label = "Failing"

    async def run(self, ctx):
        raise GenerationError("model gave up")


async def test_non_isolated_keeps_messages(app, mock_provider):
    app.registry.register(TalkerActivity)
    app.provider.context.add("user", "baseline")
    mock_provider.feed({"thinking": "t", "response": "Hello there."})

    note = await run_activity(app, app.registry.get("talker"))

    assert note == "done talking"
    contents = [m["content"] for m in app.provider.context.messages]
    assert any("baseline" in c for c in contents)
    assert any("Hello there." in c for c in contents)
    # Back on the base prompt afterwards.
    assert app.provider.context.system_prompt == app.base_prompt()


async def test_isolated_restores_context_with_one_injection(app, mock_provider):
    app.registry.register(IsolatedActivity)
    app.provider.set_system_prompt("BASE PROMPT")
    app.provider.context.add("user", "baseline")
    before = list(app.provider.context.messages)
    mock_provider.feed({"thinking": "t", "response": "In-game chatter."})

    await run_activity(app, app.registry.get("isolated"))

    msgs = list(app.provider.context.messages)
    # Original context byte-identical, plus EXACTLY one compact injection.
    assert msgs[: len(before)] == before
    assert len(msgs) == len(before) + 1
    assert msgs[-1]["role"] == "user"
    assert "[You just finished Isolated Game]" in msgs[-1]["content"]
    # No in-activity message survives.
    assert not any("In-game chatter." in m["content"] for m in msgs)
    # The snapshot also restored the pre-activity system prompt.
    assert app.provider.context.system_prompt == "BASE PROMPT"


async def test_generation_error_becomes_note_not_crash(app):
    app.registry.register(FailingActivity)

    note = await run_activity(app, app.registry.get("failing"))

    assert "ended early" in note
    rec = app.activity_tracker.records["failing"][""]
    assert rec["status"] == "no_response"


async def test_tracker_and_status_updated(app, mock_provider):
    app.registry.register(TalkerActivity)
    mock_provider.feed({"thinking": "t", "response": "Hi."})

    await run_activity(app, app.registry.get("talker"))

    rec = app.activity_tracker.records["talker"][""]
    assert rec["status"] == "completed"
    assert app.status.activity == "choosing what to do"
    assert app.stats.get("activity.talker") == 1
    assert "last:" in app.activity_tracker.status_line("talker")
