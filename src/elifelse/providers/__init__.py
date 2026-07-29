from elifelse.config import Config
from elifelse.providers.base import (
    CompletionResult,
    ContextStore,
    GenerationError,
    Provider,
    Snapshot,
)
from elifelse.providers.budget import TokenBudget
from elifelse.providers.mock import MockProvider
from elifelse.providers.openai_compat import OpenAICompatProvider


def create_provider(config: Config) -> Provider:
    """Build the configured provider. Custom backends implement Provider directly."""
    if config.provider.kind == "mock":
        return MockProvider(config)
    return OpenAICompatProvider(config)


__all__ = [
    "CompletionResult",
    "ContextStore",
    "GenerationError",
    "MockProvider",
    "OpenAICompatProvider",
    "Provider",
    "Snapshot",
    "TokenBudget",
    "create_provider",
]
