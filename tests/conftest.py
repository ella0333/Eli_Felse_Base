import pytest

from elifelse.app import App
from elifelse.config import Config
from elifelse.paths import Paths
from elifelse.persona import Persona
from elifelse.providers.mock import MockProvider


@pytest.fixture
def config(tmp_path):
    cfg = Config()
    cfg.data_dir = str(tmp_path / "data")
    cfg.provider.kind = "mock"
    cfg.provider.response_delay_min = 0
    cfg.provider.response_delay_max = 0
    # No real ChromaDB in unit tests (its embedder downloads a model on first
    # use); memory tests inject a FakeStore instead.
    cfg.memory.enabled = False
    # No day cycle by default — tests run at any wall-clock hour, and a CI run
    # at 23:00 must not fall into the bedtime flow. Day-cycle tests use a
    # fake clock and enable it explicitly.
    cfg.day_cycle.enabled = False
    # Environment ships with three real places now. Pin one so tests don't
    # spend a provider call on the first-run "where do you want to live?"
    # ask, and keep weather off so nothing reaches out to Open-Meteo.
    cfg.environment.current = "hillside_cabin"
    cfg.environment.weather = False
    return cfg


@pytest.fixture
def paths(config):
    p = Paths(config.data_dir)
    p.ensure_tree()
    return p


@pytest.fixture
def mock_provider(config):
    return MockProvider(config)


@pytest.fixture
def persona():
    return Persona(name="Testa", pronouns="she/her", personality="A test persona.")


@pytest.fixture
def app(config, persona, mock_provider):
    """A full App on a temp data dir with a MockProvider. No activities
    discovered — tests register exactly what they need."""
    return App(config, persona, provider=mock_provider)
