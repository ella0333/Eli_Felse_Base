"""Wizard tests: scripted answers in, valid config/persona files out."""

from __future__ import annotations

import yaml

from elifelse.config import load_config
from elifelse.persona import load_persona
from elifelse.wizard import run_wizard


def scripted(answers):
    it = iter(answers)

    def ask(prompt: str) -> str:
        try:
            return next(it)
        except StopIteration as e:  # pragma: no cover - test bug guard
            raise AssertionError(f"wizard asked an unscripted question: {prompt!r}") from e

    return ask


def quiet(_msg: str) -> None:
    pass


def test_local_lmstudio_defaults(tmp_path):
    answers = [
        "Ella",       # owner name
        "",           # provider choice -> default lmstudio
        "",           # server url default
        "qwen2.5-14b-instruct",  # model
        "24000",      # context tokens (suggestion)
        "n",          # lms auto-load
        "",           # daily budget default 0 (local)
        "",           # pacing -> lifelike
        "y",          # let it sleep
        "n",          # don't let it pick its bedtime -> ask for one
        "11:00 PM",   # bedtime (12h format)
        "n",          # don't let it pick its wake time -> ask for one
        "",           # wake default (shows as 8:00 AM)
        "",           # real weather -> yes
        "Nova",       # persona name
        "",           # pronouns default
        "",           # personality default
        "",           # timezone default
    ]
    rc = run_wizard(tmp_path, ask=scripted(answers), say=quiet)
    assert rc == 0

    config = load_config(tmp_path / "config.yaml")
    assert config.developer_name == "Ella"
    assert config.provider.kind == "openai_compat"
    assert config.provider.base_url == "http://127.0.0.1:1234"
    assert config.provider.model == "qwen2.5-14b-instruct"
    assert config.provider.max_context_tokens == 24000
    assert config.provider.daily_token_budget == 0
    assert config.provider.api_key_env == ""
    assert (config.provider.response_delay_min, config.provider.response_delay_max) == (1, 40)
    assert config.day_cycle.enabled and config.day_cycle.bedtime == "23:00"
    assert config.day_cycle.wake_mode == "fixed"
    assert config.day_cycle.wake_time == "08:00"

    # The default places ship in the config, and which one it starts in is
    # the agent's own first decision, so setup leaves 'current' empty.
    assert [loc.key for loc in config.environment.locations] == [
        "hillside_cabin", "city_loft", "seaside_cottage",
    ]
    assert config.environment.current == ""
    assert config.environment.weather is True

    persona = load_persona(tmp_path / "persona.yaml")
    assert persona.name == "Nova"
    assert persona.creator.name == "Ella"
    assert not (tmp_path / ".env").exists()  # no key -> no stub


def test_paid_api_requires_explicit_spend_cap(tmp_path):
    answers = [
        "",            # owner default
        "3",           # cloud provider
        "",            # url default (api.openai.com)
        "gpt-5.6-luna", # model
        "",            # context default 36000
        "not-a-number",
        "UNLIMITED",
        "n",
        "150000",
        "2",           # pacing instant
        "n",           # no sleeping (skips bedtime and wake)
        "n",           # no live weather
        "Nova", "", "", "",
        "sk-test-key-123",  # actual API key
    ]
    rc = run_wizard(tmp_path, ask=scripted(answers), say=quiet)
    assert rc == 0

    config = load_config(tmp_path / "config.yaml", env_file=tmp_path / ".env")
    assert config.provider.api_key_env == "ELIFELSE_API_KEY"
    assert config.provider.daily_token_budget == 150000
    assert (config.provider.response_delay_min, config.provider.response_delay_max) == (0, 0)
    assert config.day_cycle.enabled is False

    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "ELIFELSE_API_KEY=sk-test-key-123" in env_text


def test_paid_api_unlimited_needs_confirmation(tmp_path):
    answers = [
        "", "3", "", "m", "",
        "UNLIMITED", "y",        # confirmed unlimited
        "3", "0", "5",           # custom pacing 0..5
        "n",                     # no sleeping (skips bedtime and wake)
        "n",                     # no live weather
        "Nova", "", "", "",
        "sk-test-456",           # actual API key
    ]
    rc = run_wizard(tmp_path, ask=scripted(answers), say=quiet)
    assert rc == 0
    config = load_config(tmp_path / "config.yaml", env_file=tmp_path / ".env")
    assert config.provider.daily_token_budget == 0
    assert (config.provider.response_delay_min, config.provider.response_delay_max) == (0, 5)


def test_sleeping_with_no_bedtime_is_the_default_path(tmp_path):
    """All three sleep questions, all left at their defaults."""
    answers = [
        "",        # owner
        "4",       # mock provider
        "",        # let it sleep -> default yes
        "",        # let it pick its bedtime -> default yes
        "",        # let it pick its wake time -> default yes
        "n",       # no live weather
        "Nova", "", "", "",
    ]
    rc = run_wizard(tmp_path, ask=scripted(answers), say=quiet)
    assert rc == 0

    config = load_config(tmp_path / "config.yaml")
    assert config.day_cycle.enabled is True
    assert config.day_cycle.bedtime == ""       # nothing to count down to
    assert config.day_cycle.wake_mode == "alarm"
    assert config.day_cycle.night_start == "21:00"


def test_no_sleeping_skips_the_rest_of_the_block(tmp_path):
    """One question instead of three. An overrun here means one was still asked."""
    answers = [
        "",        # owner
        "4",       # mock provider
        "n",       # no sleeping
        "n",       # no live weather
        "Nova", "", "", "",
    ]
    rc = run_wizard(tmp_path, ask=scripted(answers), say=quiet)
    assert rc == 0

    config = load_config(tmp_path / "config.yaml")
    assert config.day_cycle.enabled is False
    assert config.day_cycle.bedtime == ""


def test_refuses_overwrite_by_default(tmp_path):
    (tmp_path / "config.yaml").write_text("developer_name: Keep\n", encoding="utf-8")
    rc = run_wizard(tmp_path, ask=scripted(["", ""]), say=quiet)  # overwrite? -> default no
    assert rc == 1
    assert "Keep" in (tmp_path / "config.yaml").read_text(encoding="utf-8")


def test_keeps_existing_persona(tmp_path):
    (tmp_path / "persona.yaml").write_text("name: Original\n", encoding="utf-8")
    answers = [
        "",        # owner
        "4",       # mock provider (skips all provider questions)
        "y",       # let it sleep
        "",        # let it pick its bedtime -> default yes
        "",        # let it pick its wake time -> default yes
        "",        # real weather -> yes
        "",        # keep existing persona -> default yes
    ]
    rc = run_wizard(tmp_path, ask=scripted(answers), say=quiet)
    assert rc == 0
    assert yaml.safe_load((tmp_path / "persona.yaml").read_text(encoding="utf-8"))["name"] == "Original"
    config = load_config(tmp_path / "config.yaml")
    assert config.provider.kind == "mock"


def test_env_stub_appends_without_clobbering(tmp_path):
    (tmp_path / ".env").write_text("OTHER=1", encoding="utf-8")
    answers = [
        "", "3", "", "m", "",
        "1000",
        "2",          # instant
        "n",          # no sleeping (skips bedtime and wake)
        "n",          # no live weather
        "Nova", "", "", "",
        "sk-test-789",  # actual API key
    ]
    rc = run_wizard(tmp_path, ask=scripted(answers), say=quiet)
    assert rc == 0
    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert env_text.startswith("OTHER=1\n")
    assert "ELIFELSE_API_KEY=sk-test-789" in env_text
