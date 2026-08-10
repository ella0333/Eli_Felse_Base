"""The built-in activities, each driven by the MockProvider. They double as
executable examples of the module API."""

from datetime import datetime, timedelta

from elifelse.activities.builtin.chat import ChatActivity
from elifelse.activities.builtin.eat import EatActivity
from elifelse.activities.builtin.environment import EnvironmentActivity
from elifelse.activities.builtin.journal import JournalActivity
from elifelse.activities.builtin.nap import NapActivity
from elifelse.activities.builtin.ponder import PonderActivity
from elifelse.channels.terminal import TerminalChannel
from elifelse.config import EnvironmentConfig, EnvironmentLocation
from elifelse.environment.system import EnvironmentSystem


def _no_eat_delay(app):
    app.config.activities["eat"] = {"meal_minutes": 0, "snack_minutes": 0}


# ~~~ discovery ~~~
async def test_builtin_discovery_and_availability(app):
    """Everything loads, and every built-in is on the menu out of the box."""
    await app.startup()  # test config: day cycle off
    assert set(app.registry.activities) >= {
        "journal", "ponder", "eat", "nap", "chat", "environment",
    }
    keys = [e["key"] for e in app.registry.menu_entries()]
    assert keys[0] == "journal"  # 'A' stays journal for mock auto mode
    assert "nap" in keys  # naps don't need a schedule, only the day cycle object
    assert "environment" in keys  # the default places ship in the config
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
        # 2. ctx.choose: food pick (B = an apple)
        {"thinking": "t", "choice": "B"},
        # 3. ctx.choose: drink pick (B = Water)
        {"thinking": "t", "choice": "B"},
        # 4. ctx.freetext: taste description
        {"thinking": "t", "response": "Crisp and cold. Perfect."},
    )
    note = await activity.run(app.registry.ctx_for(activity))

    assert "an apple" in note
    assert "water" in note  # drink included in the note
    # The first call is the raw_completion (food+drink generation, raw=True).
    assert mock_provider.calls[0]["raw"] is True
    # The food pick is a lettered menu: the enum is the letters, and the
    # invented foods only ever appear as menu text in the prompt.
    food_call = mock_provider.calls[1]
    assert food_call["schema"]["properties"]["choice"]["enum"] == ["A", "B", "C"]
    food_menu = str(food_call["messages"])
    assert "A) tomato soup (meal)" in food_menu
    assert "B) an apple (snack)" in food_menu
    assert "C) crackers (snack)" in food_menu
    # The drink menu has "No drink", "Water" (hardcoded), plus generated drinks.
    drink_call = mock_provider.calls[2]
    assert drink_call["schema"]["properties"]["choice"]["enum"] == ["A", "B", "C", "D"]
    drink_menu = str(drink_call["messages"])
    assert "A) No drink" in drink_menu
    assert "B) Water" in drink_menu
    assert "C) lemonade" in drink_menu
    assert "D) iced tea" in drink_menu
    # History recorded.
    assert "an apple" in (app.paths.activities / "eat" / "eaten.json").read_text(encoding="utf-8")


async def test_eat_no_drink(app, mock_provider):
    _no_eat_delay(app)
    app.registry.register(EatActivity)
    activity = app.registry.get("eat")
    mock_provider.feed(
        {"meal": "pasta", "snack1": "chips", "snack2": "fruit",
         "drink": "juice", "caffeine_drink": "cola"},
        {"thinking": "t", "choice": "A"},  # pasta (the meal)
        {"thinking": "t", "choice": "A"},  # No drink
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
        {"thinking": "t", "choice": "B"},  # grapes
        {"thinking": "t", "choice": "B"},  # Water
        {"thinking": "t", "response": "Sweet."},
    )
    await activity.run(app.registry.ctx_for(activity))
    # Food menu is deduped: "toast" is offered once, so there are two letters.
    food_call = mock_provider.calls[1]
    assert food_call["schema"]["properties"]["choice"]["enum"] == ["A", "B"]
    assert "A) toast (meal)" in str(food_call["messages"])
    assert "B) grapes (snack)" in str(food_call["messages"])


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


async def _nap_app(config, persona, at: datetime):
    """An App with the nap activity registered and time fully faked."""
    from elifelse.app import App
    from elifelse.providers.mock import MockProvider

    fake = FakeTime(at)
    provider = MockProvider(config)
    app = App(config, persona, provider=provider, clock=fake.now, sleep_fn=fake.sleep)
    await app.startup(discover=False)  # wires the day cycle
    app.registry.register(NapActivity)
    return app, provider, fake


async def test_nap_available_when_it_never_sleeps(app):
    """An always-on agent has no night, but it can still nap."""
    await app.startup(discover=False)  # test config: day cycle disabled
    app.registry.register(NapActivity)
    activity = app.registry.get("nap")
    assert app.daycycle is not None
    assert activity.available(app.registry.ctx_for(activity)) is True
    # ...and the bedtime hook is NOT wired, so it's never sent to bed.
    assert app.daycycle.check_bedtime not in app.scheduler.pre_menu_hooks


async def test_nap_without_sleeping_offers_no_early_night(app, mock_provider):
    """Never sleeping means no night to collide with: all durations, no early night."""
    await app.startup(discover=False)
    app.registry.register(NapActivity)
    activity = app.registry.get("nap")
    mock_provider.feed({"thinking": "sleepy", "choice": "A"})
    app.config.activities["nap"] = {"real_time": False}

    note = await activity.run(app.registry.ctx_for(activity))
    assert note == "You napped for 20 minutes and woke up on your own."
    assert mock_provider.calls[0]["schema"]["properties"]["choice"]["enum"] == ["A", "B", "C"]
    assert "Go to bed early" not in str(mock_provider.calls[0]["messages"])


async def test_nap_picks_duration_and_delegates(config, persona):
    config.day_cycle.enabled = True
    config.day_cycle.bedtime = "22:00"
    config.day_cycle.wake_mode = "fixed"
    app, provider, fake = await _nap_app(config, persona, datetime(2026, 7, 3, 14, 0))
    activity = app.registry.get("nap")
    provider.feed({"thinking": "sleepy", "choice": "A"})  # 20 minutes

    note = await activity.run(app.registry.ctx_for(activity))
    assert note == "You napped for 20 minutes and woke up on your own."
    assert sum(fake.sleeps) == 20 * 60
    # Duration options came straight from config.day_cycle.nap_durations,
    # rendered as a lettered menu with the letters as the enum. With a bedtime
    # eight hours off, all three fit, and the early-night option closes the list.
    assert provider.calls[0]["schema"]["properties"]["choice"]["enum"] == ["A", "B", "C", "D"]
    menu_text = str(provider.calls[0]["messages"])
    assert "A) 20 minutes" in menu_text
    assert "B) 1 hour" in menu_text
    assert "C) 2 hours" in menu_text
    assert "D) Go to bed for the night (sleep until 8:00 AM)" in menu_text


async def test_nap_durations_past_bedtime_are_hidden(config, persona):
    """At 21:00 with a 22:00 bedtime, only the 20-minute nap still fits."""
    config.day_cycle.enabled = True
    config.day_cycle.bedtime = "22:00"
    config.day_cycle.wake_mode = "fixed"
    config.day_cycle.night_start = "23:00"  # keep the bedtime the nearer edge
    app, provider, fake = await _nap_app(config, persona, datetime(2026, 7, 3, 21, 0))
    activity = app.registry.get("nap")
    provider.feed({"thinking": "sleepy", "choice": "A"})

    await activity.run(app.registry.ctx_for(activity))
    assert provider.calls[0]["schema"]["properties"]["choice"]["enum"] == ["A", "B"]
    menu_text = str(provider.calls[0]["messages"])
    assert "A) 20 minutes" in menu_text
    assert "B) Go to bed for the night" in menu_text
    assert "1 hour" not in menu_text
    assert "close to your 10:00 PM bedtime" in menu_text  # the shorter menu is explained


async def test_nap_early_night_sleeps_until_morning(config, persona):
    config.day_cycle.enabled = True
    config.day_cycle.bedtime = "22:00"
    config.day_cycle.wake_mode = "fixed"
    config.day_cycle.night_start = "23:00"  # still evening, so it is a choice
    app, provider, fake = await _nap_app(config, persona, datetime(2026, 7, 3, 21, 0))
    activity = app.registry.get("nap")
    provider.feed({"thinking": "worn out", "choice": "B"})  # go to bed early

    note = await activity.run(app.registry.ctx_for(activity))
    assert "brand new day" in note  # the day cycle's own wake note
    assert sum(fake.sleeps) == 11 * 3600  # 21:00 -> 08:00, straight through


async def test_nap_reads_go_to_bed_after_night_start(config, persona):
    """The whole replacement for a bedtime: one menu entry changing what it says."""
    config.day_cycle.enabled = True  # default: no bedtime, alarm wake
    app, provider, fake = await _nap_app(config, persona, datetime(2026, 7, 3, 21, 30))
    activity = app.registry.get("nap")
    ctx = app.registry.ctx_for(activity)
    assert activity.get_menu_label(ctx) == "Go to bed"

    fake.now_dt = datetime(2026, 7, 3, 14, 0)
    assert activity.get_menu_label(ctx) == "Take a nap"


async def test_go_to_bed_skips_the_duration_menu(config, persona):
    """It read "Go to bed", so it goes to bed. There is nothing to pick between."""
    config.day_cycle.enabled = True
    app, provider, fake = await _nap_app(config, persona, datetime(2026, 7, 3, 21, 30))
    activity = app.registry.get("nap")
    provider.feed({"thinking": "long night", "choice": "A"})  # the alarm menu, 4 AM

    note = await activity.run(app.registry.ctx_for(activity))
    assert "brand new day" in note
    assert sum(fake.sleeps) == 6.5 * 3600  # 21:30 -> 04:00
    # One ask, and it was the alarm, not a nap duration.
    assert len(provider.calls) == 1
    assert "how long do you want to nap" not in str(provider.calls[0]["messages"]).lower()


async def test_go_to_bed_from_the_duration_menu_also_asks_the_alarm(config, persona):
    """Both routes to bed run the same night, so both pick a wake hour."""
    config.day_cycle.enabled = True  # default: no bedtime, alarm wake
    app, provider, fake = await _nap_app(config, persona, datetime(2026, 7, 3, 14, 0))
    activity = app.registry.get("nap")
    provider.feed(
        {"thinking": "done for today", "choice": "D"},  # D = go to bed for the night
        {"thinking": "early start", "choice": "B"},     # the alarm menu, 5 AM
    )

    note = await activity.run(app.registry.ctx_for(activity))
    assert "brand new day" in note
    assert sum(fake.sleeps) == 15 * 3600  # 14:00 -> 05:00

    duration_menu, alarm_menu = (str(c["messages"]) for c in provider.calls)
    assert "D) Go to bed for the night" in duration_menu
    assert "What time do you want to wake up?" in alarm_menu
    assert "B) 5:00 AM (15 hours of sleep)" in alarm_menu


async def test_nap_durations_that_run_into_the_night_are_hidden(config, persona):
    """With no bedtime, night_start is the edge a nap must not cross."""
    config.day_cycle.enabled = True  # night_start 21:00
    app, provider, fake = await _nap_app(config, persona, datetime(2026, 7, 3, 20, 30))
    activity = app.registry.get("nap")
    provider.feed({"thinking": "sleepy", "choice": "A"})

    await activity.run(app.registry.ctx_for(activity))
    menu_text = str(provider.calls[0]["messages"])
    assert "A) 20 minutes" in menu_text
    assert "1 hour" not in menu_text
    assert "the night starts at 9:00 PM" in menu_text
    # No wake hour promised: it picks one on the way to bed.
    assert "B) Go to bed for the night" in menu_text
    assert "sleep until" not in menu_text


async def test_nap_hidden_when_no_durations_are_offered(config, persona):
    """No sleeping and no durations configured leaves nothing to choose."""
    config.day_cycle.enabled = False
    config.day_cycle.nap_durations = []
    app, provider, fake = await _nap_app(config, persona, datetime(2026, 7, 3, 14, 0))
    activity = app.registry.get("nap")
    assert activity.available(app.registry.ctx_for(activity)) is False


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
def _env(current: str = "garden"):
    return EnvironmentSystem(EnvironmentConfig(current=current, weather=False, locations=[
        EnvironmentLocation(key="garden", name="The Garden", description="Walled, quiet.",
                            latitude=52.5, longitude=13.4),
        EnvironmentLocation(key="attic", name="The Attic", description="Dusty boxes.",
                            latitude=48.9, longitude=2.4),
    ]))


async def test_environment_hidden_without_system(app):
    app.environment = None
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

    mock_provider.feed({"thinking": "t", "choice": "B"})  # The Attic
    note = await activity.run(ctx)
    assert note == "You moved to The Attic."
    assert app.environment.current_key == "attic"
    # One letter per configured location; the model reads names, not keys.
    assert mock_provider.calls[0]["schema"]["properties"]["choice"]["enum"] == ["A", "B"]
    menu_text = str(mock_provider.calls[0]["messages"])
    assert "A) The Garden (you are here)" in menu_text
    assert "B) The Attic" in menu_text


async def test_environment_staying_put(app, mock_provider):
    app.environment = _env()
    app.registry.register(EnvironmentActivity)
    activity = app.registry.get("environment")
    mock_provider.feed({"thinking": "t", "choice": "A"})  # The Garden
    note = await activity.run(app.registry.ctx_for(activity))
    assert "decided to stay" in note
    assert app.environment.current_key == "garden"


async def test_first_run_asks_for_an_environment(app, mock_provider):
    """No environment chosen yet, so the agent picks before it sees the main menu."""
    app.environment = _env(current="")
    assert app.environment.chosen is False
    mock_provider.feed(
        {"thinking": "somewhere quiet", "choice": "B"},  # the opening choice
        {"thinking": "write", "choice": "A"},            # the first real menu
    )
    app.registry.register(JournalActivity)

    await app.controller.main_loop(max_iterations=1)
    assert app.environment.current_key == "attic"
    assert app.environment.chosen is True
    opening = str(mock_provider.calls[0]["messages"])
    assert "This is where you will exist until you change it again" in opening
    assert "(you are here)" not in opening  # it isn't anywhere yet


async def test_a_restored_place_is_not_asked_about(app, mock_provider):
    """Loading a save already set an environment, so the loop goes straight in."""
    app.environment = _env(current="")
    app.environment.set_current("attic")  # what a crash or save restore does
    assert app.environment.chosen is True
    mock_provider.feed({"thinking": "write", "choice": "A"})
    app.registry.register(JournalActivity)

    await app.controller.main_loop(max_iterations=1)
    # The very first thing asked is the menu, not "where do you want to live?"
    assert "What would you like to do next?" in str(mock_provider.calls[0]["messages"])
