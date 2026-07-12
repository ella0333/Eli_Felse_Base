"""The built-in activities, each driven by the MockProvider. They double as
executable examples of the module API."""

from datetime import datetime, timedelta

from elifelse.activities.builtin.chat import ChatActivity
from elifelse.activities.builtin.eat import EatActivity
from elifelse.activities.builtin.environment import EnvironmentActivity
from elifelse.activities.builtin.nap import NapActivity
from elifelse.activities.builtin.ponder import PonderActivity
from elifelse.channels.terminal import TerminalChannel
from elifelse.config import EnvironmentConfig, EnvironmentLocation
from elifelse.environment.system import EnvironmentSystem


def _no_eat_delay(app):
    app.config.activities["eat"] = {"meal_minutes": 0, "snack_minutes": 0}


# ~~~ discovery ~~~
async def test_builtin_discovery_and_availability(app):
    """Everything loads; nap/environment hide when their subsystems are off."""
    await app.startup()  # test config: day cycle off, no environment locations
    assert set(app.registry.activities) >= {
        "journal", "ponder", "eat", "nap", "chat", "environment",
    }
    keys = [e["key"] for e in app.registry.menu_entries()]
    assert keys[0] == "journal"  # 'A' stays journal for mock auto mode
    assert "nap" not in keys  # day cycle disabled
    assert "environment" not in keys  # no locations configured
    assert "chat" in keys  # its startup registered the terminal channel
    assert isinstance(app.channels["terminal"], TerminalChannel)


# ~~~ ponder ~~~
async def test_ponder_loops_until_done(app, mock_provider):
    app.registry.register(PonderActivity)
    activity = app.registry.get("ponder")
    mock_provider.feed(
        {"thinking": "hm", "response": "I want to read more.", "return_to_menu": False},
        {"thinking": "hm", "response": "Starting tonight, actually.", "return_to_menu": True},
    )
    note = await activity.run(app.registry.ctx_for(activity))
    assert "(2 rounds)" in note


async def test_ponder_round_cap(app, mock_provider):
    """A model that never sets return_to_menu can't ponder forever."""
    app.registry.register(PonderActivity)
    activity = app.registry.get("ponder")
    mock_provider.feed(
        *[{"thinking": "t", "response": f"Thought {i}.", "return_to_menu": False}
          for i in range(9)]
    )
    note = await activity.run(app.registry.ctx_for(activity))
    assert "(5 rounds)" in note  # MAX_ROUNDS


# ~~~ eat ~~~
async def test_eat_full_flow(app, mock_provider):
    _no_eat_delay(app)
    app.registry.register(EatActivity)
    activity = app.registry.get("eat")
    mock_provider.feed(
        # 1. raw_completion: food + drink ideas (behind the scenes, no character)
        {"meal": "tomato soup", "snack1": "an apple", "snack2": "crackers",
         "drink": "lemonade", "caffeine_drink": "iced tea"},
        # 2. ctx.choose: food pick
        {"thinking": "t", "choice": "an apple"},
        # 3. ctx.choose: drink pick
        {"thinking": "t", "choice": "Water"},
        # 4. ctx.freetext: taste description
        {"thinking": "t", "response": "Crisp and cold. Perfect."},
    )
    note = await activity.run(app.registry.ctx_for(activity))

    assert "an apple" in note
    assert "water" in note  # drink included in the note
    # The first call is the raw_completion (food+drink generation, raw=True).
    assert mock_provider.calls[0]["raw"] is True
    # The food pick went through a schema whose enum is exactly the invented foods.
    choose_schema = mock_provider.calls[1]["schema"]
    assert choose_schema["properties"]["choice"]["enum"] == [
        "tomato soup", "an apple", "crackers",
    ]
    # The drink pick has "No drink", "Water" (hardcoded), plus generated drinks.
    drink_schema = mock_provider.calls[2]["schema"]
    assert drink_schema["properties"]["choice"]["enum"] == [
        "No drink", "Water", "lemonade", "iced tea",
    ]
    # History recorded.
    assert "an apple" in (app.paths.activities / "eat" / "eaten.json").read_text(encoding="utf-8")


async def test_eat_no_drink(app, mock_provider):
    _no_eat_delay(app)
    app.registry.register(EatActivity)
    activity = app.registry.get("eat")
    mock_provider.feed(
        {"meal": "pasta", "snack1": "chips", "snack2": "fruit",
         "drink": "juice", "caffeine_drink": "cola"},
        {"thinking": "t", "choice": "pasta"},
        {"thinking": "t", "choice": "No drink"},
        {"thinking": "t", "response": "Warm and filling."},
    )
    note = await activity.run(app.registry.ctx_for(activity))
    assert "pasta" in note
    assert "drink" not in note.lower()  # "No drink" omitted from the note


async def test_eat_deduplicates_invented_foods(app, mock_provider):
    _no_eat_delay(app)
    app.registry.register(EatActivity)
    activity = app.registry.get("eat")
    mock_provider.feed(
        {"meal": "toast", "snack1": "toast", "snack2": "grapes",
         "drink": "tea", "caffeine_drink": "coffee"},
        {"thinking": "t", "choice": "grapes"},
        {"thinking": "t", "choice": "Water"},
        {"thinking": "t", "response": "Sweet."},
    )
    await activity.run(app.registry.ctx_for(activity))
    # Food enum is deduped: "toast" appears once.
    assert mock_provider.calls[1]["schema"]["properties"]["choice"]["enum"] == ["toast", "grapes"]


# ~~~ nap ~~~
class FakeTime:
    def __init__(self, start: datetime) -> None:
        self.now_dt = start
        self.sleeps: list[float] = []

    def now(self) -> datetime:
        return self.now_dt

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now_dt += timedelta(seconds=seconds)


async def test_nap_hidden_without_day_cycle(app):
    app.registry.register(NapActivity)
    activity = app.registry.get("nap")
    assert activity.available(app.registry.ctx_for(activity)) is False


async def test_nap_picks_duration_and_delegates(config, persona):
    from elifelse.app import App
    from elifelse.providers.mock import MockProvider

    config.day_cycle.enabled = True
    fake = FakeTime(datetime(2026, 7, 3, 14, 0))
    provider = MockProvider(config)
    app = App(config, persona, provider=provider, clock=fake.now, sleep_fn=fake.sleep)
    await app.startup(discover=False)  # wires the day cycle

    app.registry.register(NapActivity)
    activity = app.registry.get("nap")
    provider.feed({"thinking": "sleepy", "choice": "20 minutes"})

    note = await activity.run(app.registry.ctx_for(activity))
    assert note == "You napped for 20 minutes and woke up on your own."
    assert sum(fake.sleeps) == 20 * 60
    # Duration options came straight from config.day_cycle.nap_durations.
    enum = provider.calls[0]["schema"]["properties"]["choice"]["enum"]
    assert enum == ["20 minutes", "1 hour", "2 hours"]


# ~~~ chat ~~~
def _wire_chat(app, timeout: float = 0.05) -> TerminalChannel:
    app.config.activities["chat"] = {"timeout_seconds": timeout}
    channel = TerminalChannel(developer_name=app.config.developer_name, agent_name="Testa")
    app.channels["terminal"] = channel
    app.registry.register(ChatActivity)
    return channel


async def test_chat_answers_waiting_message(app, mock_provider, capsys):
    channel = _wire_chat(app)
    channel.push("hey, how was your day?")
    activity = app.registry.get("chat")
    mock_provider.feed(
        {"thinking": "t", "response": "Pretty good! I wrote a bit.", "return_to_menu": True},
    )

    note = await activity.run(app.registry.ctx_for(activity))
    assert note == "You wrapped up a chat with Developer."
    # The person's message reached the model as prompt text...
    assert "hey, how was your day?" in str(mock_provider.calls[0]["messages"])
    # ...and the agent's reply was delivered to the terminal.
    assert "Testa: Pretty good! I wrote a bit." in capsys.readouterr().out


async def test_chat_multi_turn_then_timeout(app, mock_provider):
    channel = _wire_chat(app)
    channel.push("hi!")
    activity = app.registry.get("chat")
    mock_provider.feed(
        {"thinking": "t", "response": "Hi! What's up?", "return_to_menu": False},
        {"thinking": "t", "response": "Ha, same here.", "return_to_menu": False},
    )

    # One human reply, then silence -> the timeout ends the chat gracefully.
    channel.push("not much, just tinkering")
    note = await activity.run(app.registry.ctx_for(activity))
    assert "stepped away" in note


async def test_chat_greets_when_nothing_waiting(app, mock_provider):
    _wire_chat(app)
    activity = app.registry.get("chat")
    mock_provider.feed({"thinking": "t", "response": "Hello!", "return_to_menu": True})

    await activity.run(app.registry.ctx_for(activity))
    assert "open the conversation" in str(mock_provider.calls[0]["messages"])


async def test_chat_survey_updates_profile(app, mock_provider):
    """Via the full lifecycle: get_subject makes the survey profile the person's."""
    from elifelse.innerlife.system import InnerLife
    from elifelse.loop.lifecycle import run_activity

    app.innerlife = InnerLife(mock_provider, app.schemas, app.paths, app.clock)
    _wire_chat(app)
    mock_provider.feed(
        {"thinking": "t", "response": "Hey you!", "return_to_menu": True},
        {"thinking": "t", "emotion": "warm", "feeling": "love"},  # chat survey
    )

    await run_activity(app, app.registry.get("chat"))
    profile = app.innerlife.profiles.get("Developer")
    assert profile["current_feeling"] == "love"


# ~~~ environment ~~~
def _env():
    return EnvironmentSystem(EnvironmentConfig(locations=[
        EnvironmentLocation(key="garden", name="The Garden", description="Walled, quiet.",
                            latitude=52.5, longitude=13.4),
        EnvironmentLocation(key="attic", name="The Attic", description="Dusty boxes.",
                            latitude=48.9, longitude=2.4),
    ]))


async def test_environment_hidden_without_system(app):
    app.registry.register(EnvironmentActivity)
    activity = app.registry.get("environment")
    assert activity.available(app.registry.ctx_for(activity)) is False


async def test_environment_move(app, mock_provider):
    app.environment = _env()
    app.registry.register(EnvironmentActivity)
    activity = app.registry.get("environment")
    ctx = app.registry.ctx_for(activity)
    assert activity.available(ctx) is True
    assert activity.get_status(ctx) == "currently: The Garden"

    mock_provider.feed({"thinking": "t", "choice": "attic"})
    note = await activity.run(ctx)
    assert note == "You moved to The Attic."
    assert app.environment.current_key == "attic"
    # The choice enum is exactly the configured location keys.
    enum = mock_provider.calls[0]["schema"]["properties"]["choice"]["enum"]
    assert enum == ["garden", "attic"]


async def test_environment_staying_put(app, mock_provider):
    app.environment = _env()
    app.registry.register(EnvironmentActivity)
    activity = app.registry.get("environment")
    mock_provider.feed({"thinking": "t", "choice": "garden"})
    note = await activity.run(app.registry.ctx_for(activity))
    assert "decided to stay" in note
    assert app.environment.current_key == "garden"
