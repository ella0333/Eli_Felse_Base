"""persona.yaml — the character. One user-written file; nothing personal ships here."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError

from elifelse.config import ConfigError, _format_validation_error


class Creator(BaseModel):
    name: str = ""
    relationship: str = ""


class Flavor(BaseModel):
    mention_model: bool = True
    mention_hardware: bool = False


class Persona(BaseModel):
    name: str
    pronouns: str = ""
    personality: str = ""
    backstory: str = ""
    creator: Creator = Field(default_factory=Creator)
    timezone: str = "UTC"
    flavor: Flavor = Field(default_factory=Flavor)


def load_persona(path: Path | str) -> Persona:
    path = Path(path)
    if not path.exists():
        raise ConfigError(
            f"Persona file not found: {path}\n"
            f"Run 'elifelse init' to create one, or copy persona.example.yaml."
        )
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise ConfigError(f"{path} is not valid YAML: {e}") from e
    try:
        return Persona.model_validate(raw)
    except ValidationError as e:
        raise ConfigError(_format_validation_error(e, str(path))) from e
