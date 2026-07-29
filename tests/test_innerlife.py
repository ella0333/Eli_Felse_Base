"""Inner life: surveys set the current emotion, chat surveys update profiles,
self-facts persist and land in the base prompt."""

import json

import pytest

from elifelse.activities.base import Activity
from elifelse.innerlife.selffacts import SelfFacts
from elifelse.innerlife.system import InnerLife
from elifelse.structured.registry import SchemaRegistry


@pytest.fixture
def innerlife(mock_provider, paths):
    return InnerLife(mock_provider, SchemaRegistry(), paths)


async def test_simple_survey_sets_emotion_and_logs(innerlife, mock_provider, paths):
    mock_provider.feed({"thinking": "t", "emotion": "content, a little sleepy"})

    await innerlife.run_survey("simple", "your journal", "journal")

    assert innerlife.current_emotion == "content, a little sleepy"
    lines = (paths.surveys / "surveys.jsonl").read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[0])
    assert record["activity"] == "journal"
    assert record["type"] == "simple"
    assert record["emotion"] == "content, a little sleepy"


async def test_chat_survey_updates_profile(innerlife, mock_provider):
    mock_provider.feed({"thinking": "t", "emotion": "warm", "feeling": "like"})
    await innerlife.run_survey("chat", "Sam", "chat")

    profile = innerlife.profiles.get("Sam")
    assert profile["current_feeling"] == "like"
    assert profile["interactions"] == 1

    mock_provider.feed({"thinking": "t", "emotion": "glowy", "feeling": "love"})
    await innerlife.run_survey("chat", "Sam", "chat")

    profile = innerlife.profiles.get("Sam")
    assert profile["current_feeling"] == "love"
    assert profile["interactions"] == 2
    assert [h["feeling"] for h in profile["history"]] == ["like", "love"]


async def test_out_of_enum_feeling_rejected(innerlife, mock_provider):
    """'adore' isn't in the feeling enum — the validation loop must retry."""
    mock_provider.feed(
        {"thinking": "t", "emotion": "warm", "feeling": "adore"},
        {"thinking": "t", "emotion": "warm", "feeling": "love"},
    )
    await innerlife.run_survey("chat", "Sam", "chat")
    assert innerlife.profiles.get("Sam")["current_feeling"] == "love"


async def test_failed_survey_is_skipped_silently(innerlife, mock_provider):
    mock_provider.feed(*["garbage"] * 5)
    await innerlife.run_survey("simple", "a walk", "walk")
    assert innerlife.current_emotion == ""


def test_self_facts_persist_and_dedupe(paths):
    facts = SelfFacts(paths.state / "self_facts.json")
    facts.add("I like rainy days.")
    facts.add("I like rainy days.")  # duplicate ignored
    facts.add("I'm reading Moby-Dick.")
    assert facts.facts == ["I like rainy days.", "I'm reading Moby-Dick."]
    assert "- I like rainy days." in facts.prompt_block()

    reloaded = SelfFacts(paths.state / "self_facts.json")
    assert reloaded.facts == facts.facts


def test_self_facts_cap(paths):
    facts = SelfFacts(paths.state / "self_facts.json")
    for i in range(20):
        facts.add(f"Fact number {i}.")
    assert len(facts.facts) == 15
    assert facts.facts[0] == "Fact number 5."  # oldest fell off


async def test_survey_runs_via_lifecycle_and_colors_prompt(app, mock_provider):
    from elifelse.loop.lifecycle import run_activity

    class Walk(Activity):
        key = "walk"
        menu_label = "Take a walk"
        survey = "simple"

        async def run(self, ctx):
            await ctx.freetext("How was the walk?")
            return "walked"

    app.innerlife = InnerLife(mock_provider, app.schemas, app.paths, app.clock)
    app.registry.register(Walk)
    mock_provider.feed(
        {"thinking": "t", "response": "Lovely air out there."},
        {"thinking": "t", "emotion": "refreshed"},
    )

    await run_activity(app, app.registry.get("walk"))

    assert app.innerlife.current_emotion == "refreshed"
    assert "You're currently feeling: refreshed" in app.base_prompt()
