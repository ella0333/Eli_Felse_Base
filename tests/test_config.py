"""Config + persona loading: valid files parse, errors name the exact key."""

import pytest

from elifelse.config import Config, ConfigError, load_config
from elifelse.persona import load_persona


def test_example_config_parses(tmp_path):
    # The committed example must always be loadable.
    from pathlib import Path

    example = Path(__file__).parent.parent / "config.example.yaml"
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
    cfg = load_config(cfg_file)
    assert cfg.provider.kind == "openai_compat"
    assert cfg.memory.batch_size == 6
    assert cfg.environment.locations[0].key == "hillside_cabin"


def test_example_persona_parses(tmp_path):
    from pathlib import Path

    example = Path(__file__).parent.parent / "persona.example.yaml"
    p_file = tmp_path / "persona.yaml"
    p_file.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
    persona = load_persona(p_file)
    assert persona.name == "Eli"
    assert persona.flavor.mention_hardware is False


def test_missing_config_file_is_clear(tmp_path):
    with pytest.raises(ConfigError, match="elifelse init"):
        load_config(tmp_path / "nope.yaml")


def test_invalid_key_named_in_error(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("provider:\n  kind: teapot\n", encoding="utf-8")
    with pytest.raises(ConfigError, match=r"provider\.kind"):
        load_config(cfg_file)


def test_bad_bedtime_named(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("day_cycle:\n  bedtime: '25:99'\n", encoding="utf-8")
    with pytest.raises(ConfigError, match=r"day_cycle\.bedtime"):
        load_config(cfg_file)


def test_api_key_env_resolution(monkeypatch, tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "provider:\n  api_key_env: 'TEST_ELIFELSE_KEY'\n", encoding="utf-8"
    )
    cfg = load_config(cfg_file)
    with pytest.raises(ConfigError, match="TEST_ELIFELSE_KEY"):
        cfg.provider.api_key()
    monkeypatch.setenv("TEST_ELIFELSE_KEY", "abc123")
    assert cfg.provider.api_key() == "abc123"


def test_params_fallback_to_default():
    cfg = Config()
    p = cfg.params_for("some-unknown-model")
    assert p.temperature == 0.7
    assert p.max_tokens_raw == 4000


def test_defaults_are_sane():
    cfg = Config()
    assert cfg.provider.daily_token_budget == 0
    assert cfg.day_cycle.enabled is True
    assert cfg.memory.direct_threshold == 0.65
