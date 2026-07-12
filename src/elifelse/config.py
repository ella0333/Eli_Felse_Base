"""Config loading: config.yaml -> pydantic models, .env -> secrets.

Validation errors name the exact missing/invalid key so users can fix them.
Secrets never live in config.yaml — it references environment variable NAMES only.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError, field_validator


class ConfigError(Exception):
    """Raised with a human-readable message naming the offending config key."""


class ModelParams(BaseModel):
    temperature: float = 0.7
    temperature_raw: float = 0.3
    top_p: float = 0.95
    top_k: int = 0
    repeat_penalty: float = 1.05
    max_tokens: int = 3000
    max_tokens_raw: int = 4000
    chat_template_kwargs: dict[str, Any] | None = None


class ProviderQuirks(BaseModel):
    no_think_suffix: bool = False


class ProviderConfig(BaseModel):
    kind: str = "openai_compat"  # "openai_compat" | "mock"
    base_url: str = "http://127.0.0.1:1234/v1"
    api_key_env: str = ""  # NAME of the env var holding the key; "" = no key (local)
    model: str = "default"
    utility_model: str = ""  # "" = use the main model for background work
    max_context_tokens: int = 36000
    chars_per_token: int = 3
    request_timeout: int = 300
    response_delay_min: int = 1
    response_delay_max: int = 40
    daily_token_budget: int = 0  # 0 = unlimited; auto-sleep when hit
    lmstudio_loader: bool = False
    quirks: ProviderQuirks = Field(default_factory=ProviderQuirks)

    @field_validator("kind")
    @classmethod
    def _known_kind(cls, v: str) -> str:
        if v not in ("openai_compat", "mock"):
            raise ValueError("must be 'openai_compat' or 'mock'")
        return v

    def api_key(self) -> str:
        """Resolve the API key from the environment. Empty string = no key."""
        if not self.api_key_env:
            return ""
        val = os.environ.get(self.api_key_env, "")
        if not val:
            raise ConfigError(
                f"provider.api_key_env is set to '{self.api_key_env}' but that "
                f"environment variable is empty. Add it to your .env file."
            )
        if val == "PASTE-YOUR-API-KEY-HERE":
            raise ConfigError(
                f"provider.api_key_env '{self.api_key_env}' still has the setup "
                f"wizard placeholder. Open your .env file and replace "
                f"PASTE-YOUR-API-KEY-HERE with your actual API key."
            )
        return val


class DayCycleConfig(BaseModel):
    enabled: bool = True
    bedtime: str = "22:00"
    wake_time: str = "08:00"
    nap_durations: list[int] = Field(default_factory=lambda: [20, 60, 120])

    @field_validator("bedtime", "wake_time")
    @classmethod
    def _hhmm(cls, v: str) -> str:
        parts = v.split(":")
        if len(parts) != 2 or not all(p.isdigit() for p in parts):
            raise ValueError("must be 'HH:MM' (24h)")
        h, m = int(parts[0]), int(parts[1])
        if not (0 <= h < 24 and 0 <= m < 60):
            raise ValueError("must be a valid 24h time 'HH:MM'")
        return v


class MemoryConfig(BaseModel):
    enabled: bool = True
    batch_size: int = 6
    direct_threshold: float = 0.65
    global_threshold: float = 0.85
    max_recall: int = 3
    max_facts: int = 15


class SummaryConfig(BaseModel):
    chunk_chars: int = 400_000


class InnerLifeConfig(BaseModel):
    enabled: bool = True


class EnvironmentLocation(BaseModel):
    key: str
    name: str
    description: str
    latitude: float
    longitude: float


class EnvironmentConfig(BaseModel):
    enabled: bool = True
    weather: bool = True
    current: str = ""
    locations: list[EnvironmentLocation] = Field(default_factory=list)


class BackupConfig(BaseModel):
    enabled: bool = True


class StatusConfig(BaseModel):
    websocket_enabled: bool = False
    websocket_port: int = 8765


class DashboardConfig(BaseModel):
    enabled: bool = True
    port: int = 8080


class LoggingConfig(BaseModel):
    level: str = "INFO"


class Config(BaseModel):
    developer_name: str = "Developer"
    data_dir: str = "./data"
    provider: ProviderConfig = Field(default_factory=ProviderConfig)
    model_params: dict[str, ModelParams] = Field(default_factory=lambda: {"default": ModelParams()})
    day_cycle: DayCycleConfig = Field(default_factory=DayCycleConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    summary: SummaryConfig = Field(default_factory=SummaryConfig)
    inner_life: InnerLifeConfig = Field(default_factory=InnerLifeConfig)
    environment: EnvironmentConfig = Field(default_factory=EnvironmentConfig)
    backup: BackupConfig = Field(default_factory=BackupConfig)
    status: StatusConfig = Field(default_factory=StatusConfig)
    dashboard: DashboardConfig = Field(default_factory=DashboardConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    activities: dict[str, dict[str, Any]] = Field(default_factory=dict)

    def params_for(self, model: str) -> ModelParams:
        """Generation params for a model, falling back to the 'default' entry."""
        return self.model_params.get(model) or self.model_params.get("default") or ModelParams()


def _format_validation_error(err: ValidationError, source: str) -> str:
    lines = [f"{source} is invalid:"]
    for e in err.errors():
        loc = ".".join(str(p) for p in e["loc"]) or "(root)"
        lines.append(f"  - key '{loc}': {e['msg']}")
    return "\n".join(lines)


def load_config(path: Path | str, env_file: Path | str | None = None) -> Config:
    """Load and validate config.yaml. Also loads .env (secrets) if present."""
    path = Path(path)
    if env_file is not None:
        load_dotenv(env_file)
    else:
        load_dotenv(path.parent / ".env")

    if not path.exists():
        raise ConfigError(
            f"Config file not found: {path}\n"
            f"Run 'elifelse init' to create one, or copy config.example.yaml."
        )
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise ConfigError(f"{path} is not valid YAML: {e}") from e
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} must contain a YAML mapping at the top level.")
    try:
        return Config.model_validate(raw)
    except ValidationError as e:
        raise ConfigError(_format_validation_error(e, str(path))) from e
