"""`elifelse init` — interactive setup wizard.

Asks plain-language questions and writes config.yaml + persona.yaml (and a .env
stub when a paid API key is involved). Every generated file is validated through
the same pydantic models the runtime uses, so the wizard can never produce a
config that `elifelse run` rejects.

The two questions the wizard is strict about:
- context clamp: the framework budgets prompts against this number, so it must
  not exceed what the model server is actually configured for
- spend cap: on a paid API (an API key is involved) there is NO silent default —
  the user must either give a daily token budget or explicitly type UNLIMITED
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import yaml

from elifelse.config import Config, ProviderConfig
from elifelse.persona import Persona
from elifelse.textutils import print_system

AskFn = Callable[[str], str]

_TIME_24_RE = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d$")
_TIME_12_RE = re.compile(
    r"^(1[0-2]|0?[1-9]):([0-5]\d)\s*(AM|PM|am|pm|Am|Pm|aM|pM)$"
)


def _to_24h(raw: str) -> str:
    """Normalize any accepted time input to HH:MM 24h format."""
    raw = raw.strip()
    if _TIME_24_RE.match(raw):
        parts = raw.split(":")
        return f"{int(parts[0]):02d}:{parts[1]}"
    m = _TIME_12_RE.match(raw)
    if m:
        h, mn, period = int(m.group(1)), m.group(2), m.group(3).upper()
        if period == "AM":
            h = 0 if h == 12 else h
        else:
            h = h if h == 12 else h + 12
        return f"{h:02d}:{mn}"
    raise ValueError(raw)


def _to_12h(hhmm24: str) -> str:
    """Convert 24h HH:MM to 12h AM/PM display string."""
    h, m = int(hhmm24.split(":")[0]), int(hhmm24.split(":")[1])
    suffix = "AM" if h < 12 else "PM"
    display_h = h % 12 or 12
    return f"{display_h}:{m:02d} {suffix}"


class WizardIO:
    """Thin prompt layer so tests can script answers."""

    def __init__(self, ask: AskFn = input, say: Callable[[str], None] = print_system):
        self._ask = ask
        self.say = say

    def text(self, prompt: str, default: str = "", show_default: bool = True) -> str:
        suffix = f" ({default})" if default and show_default else ""
        answer = self._ask(f"{prompt}{suffix}: ").strip()
        return answer or default

    def yesno(self, prompt: str, default: bool = True) -> bool:
        hint = "Y/n" if default else "y/N"
        while True:
            answer = self._ask(f"{prompt} ({hint}): ").strip().lower()
            if not answer:
                return default
            if answer in ("y", "yes"):
                return True
            if answer in ("n", "no"):
                return False
            self.say("please answer y or n")

    def integer(self, prompt: str, default: int | None = None, minimum: int = 0,
                show_default: bool = True) -> int:
        suffix = f" ({default})" if default is not None and show_default else ""
        while True:
            answer = self._ask(f"{prompt}{suffix}: ").strip()
            if not answer and default is not None:
                return default
            if answer.lstrip("-").isdigit() and int(answer) >= minimum:
                return int(answer)
            self.say(f"please enter a whole number >= {minimum}")

    def choice(self, prompt: str, options: list[tuple[str, str]], default: str) -> str:
        """options = [(key, label), ...]; returns the chosen key."""
        self.say(prompt)
        for i, (_, label) in enumerate(options, 1):
            self.say(f"  {i}. {label}")
        keys = [k for k, _ in options]
        default_num = keys.index(default) + 1
        while True:
            answer = self._ask(f"choose 1-{len(options)} ({default_num}): ").strip()
            if not answer:
                return default
            if answer.isdigit() and 1 <= int(answer) <= len(options):
                return keys[int(answer) - 1]
            self.say(f"please enter a number from 1 to {len(options)}")

    def hhmm(self, prompt: str, default: str) -> str:
        default_display = _to_12h(default)
        while True:
            answer = self._ask(f"{prompt} ({default_display}): ").strip()
            if not answer:
                return default
            if _TIME_24_RE.match(answer) or _TIME_12_RE.match(answer):
                return _to_24h(answer)
            self.say("use AM/PM like 10:30 PM, or 24h like 22:30")


def _ask_provider(io: WizardIO) -> ProviderConfig:
    kind = io.choice(
        "Where does the model run?",
        [
            ("lmstudio", "LM Studio on this computer (local, free)"),
            ("ollama", "Ollama on this computer (local, free)"),
            ("cloud", "A paid API (OpenRouter, OpenAI, Anthropic, etc.)"),
            ("mock", "No model, canned demo responses (just looking around)"),
        ],
        default="lmstudio",
    )
    if kind == "mock":
        return ProviderConfig(kind="mock")

    defaults = {
        "lmstudio": "http://127.0.0.1:1234",
        "ollama": "http://127.0.0.1:11434",
        "cloud": "https://api.openai.com/v1",
    }
    hints = {
        "lmstudio": "  (In LM Studio: Developer tab → look for the server URL, e.g. http://127.0.0.1:1234)",
        "ollama": "  (Ollama's default is http://127.0.0.1:11434)",
    }
    if kind in hints:
        io.say(hints[kind])
    provider = ProviderConfig(kind="openai_compat")
    provider.base_url = io.text("Server URL", default=defaults[kind])
    provider.model = io.text(
        "Model identifier (e.g. 'openai/gpt-5.6-luna')",
        default="default" if kind != "cloud" else "",
    ) or "default"

    if kind == "cloud":
        provider.api_key_env = "ELIFELSE_API_KEY"

    io.say("")
    io.say("Context clamp: how many tokens the framework reserves for every prompt.")
    io.say("Set this at or below what your model/server actually supports.")
    io.say("The default of 36000 works for most local setups — raise or lower as needed.")
    provider.max_context_tokens = io.integer(
        "Context tokens (suggestion: 36000)", default=36000, minimum=2000,
        show_default=False,
    )

    if kind == "lmstudio":
        provider.lmstudio_loader = io.yesno(
            "Auto-load the model in LM Studio via the 'lms' CLI (with this context length)?",
            default=False,
        )

    # Spend cap — mandatory decision on paid APIs, optional on local.
    io.say("")
    if provider.api_key_env:
        io.say("SPEND CAP — this agent runs all day and calls the API on its own.")
        io.say("On a paid API you must set a daily token budget (all calls count).")
        io.say("When the budget runs out, the agent sleeps until the daily reset.")
        while True:
            answer = io.text(
                "Daily token budget (a number, e.g. 200000), or type UNLIMITED"
            )
            if answer.upper() == "UNLIMITED":
                if io.yesno(
                    "Really run an autonomous agent on a paid API with NO spend cap?",
                    default=False,
                ):
                    provider.daily_token_budget = 0
                    break
            elif answer.isdigit() and int(answer) > 0:
                provider.daily_token_budget = int(answer)
                break
            else:
                io.say("enter a positive number, or the word UNLIMITED")
    else:
        budget = io.integer(
            "Daily token budget (0 = unlimited; fine for local models)", default=0
        )
        provider.daily_token_budget = budget

    # Pacing.
    io.say("")
    io.say("Response pacing adds a randomized delay before each in-character reply.")
    io.say("If you're running a model locally, this gives your GPU time to rest")
    io.say("between calls. It also makes response times feel more natural.")
    pacing = io.choice(
        "Choose a pacing style:",
        [
            ("lifelike", "Lifelike — 1 to 40 seconds (recommended)"),
            ("instant", "Instant — no artificial delay"),
            ("custom", "Custom — pick your own min/max seconds"),
        ],
        default="lifelike",
    )
    if pacing == "lifelike":
        provider.response_delay_min, provider.response_delay_max = 1, 40
    elif pacing == "instant":
        provider.response_delay_min, provider.response_delay_max = 0, 0
    else:
        lo = io.integer("Minimum delay seconds", default=1)
        hi = io.integer("Maximum delay seconds", default=40, minimum=lo)
        provider.response_delay_min, provider.response_delay_max = lo, hi
    return provider


def _ask_persona(io: WizardIO, developer_name: str = "Developer") -> Persona:
    io.say("")
    io.say("Now the character. Give your model a name and personality — this is")
    io.say("who the AI will be. Short answers are fine; you can flesh out")
    io.say("persona.yaml in any text editor later.")
    name = ""
    while not name:
        name = io.text("What should your model be called?")
    persona = Persona(name=name)
    persona.pronouns = io.text("Pronouns (e.g. he/him)", default="he/him", show_default=False)
    persona.personality = io.text(
        "One or two sentences of personality",
        default="Curious and even-keeled. Speaks plainly, with occasional dry humor.",
    )
    persona.creator.name = developer_name
    persona.timezone = io.text("Timezone (IANA name)", default="America/New_York")
    return persona


async def _probe_api(config: Config) -> dict[str, Any]:
    """Send a tiny test request to the configured API and return a diagnostic dict.

    Returns {"ok": True} on success, or {"ok": False, "issue": ..., "detail": ...}
    describing what went wrong.  May also return {"ok": True, "fixed_model": ...}
    or {"ok": True, "blocked_params": [...]} when auto-recovery succeeded.
    """
    from urllib.parse import urlparse

    from elifelse.providers.openai_compat import (
        _ANTHROPIC_HOSTS,
        _BACKTICK_PARAM_RE,
        _BAD_PARAM_RE,
        _ESSENTIAL_PARAMS,
        _PARAM_ALIASES,
    )

    pconf = config.provider
    if pconf.kind == "mock":
        return {"ok": True}

    base_url = pconf.base_url.rstrip("/")
    if not base_url.endswith("/v1"):
        base_url += "/v1"

    host = (urlparse(base_url).hostname or "").lower()
    is_anthropic = any(host == h or host.endswith("." + h) for h in _ANTHROPIC_HOSTS)

    headers: dict[str, str] = {"Content-Type": "application/json"}
    try:
        key = pconf.api_key()
        if is_anthropic:
            headers["anthropic-version"] = "2023-06-01"
            if key:
                headers["x-api-key"] = key
        elif key:
            headers["Authorization"] = f"Bearer {key}"
    except Exception:
        return {"ok": False, "issue": "api_key", "detail": "API key not available yet"}

    mp = config.params_for(pconf.model)
    model = pconf.model

    if is_anthropic:
        endpoint = f"{base_url}/messages"
        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": "say ok"}],
            "max_tokens": 5,
            "temperature": mp.temperature,
            "stream": False,
        }
    else:
        endpoint = f"{base_url}/chat/completions"
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": "say ok"}],
            "temperature": mp.temperature,
            "top_p": mp.top_p,
            "max_tokens": 5,
            "stream": False,
            "repeat_penalty": mp.repeat_penalty,
        }
        if mp.top_k:
            payload["top_k"] = mp.top_k

    result: dict[str, Any] = {"ok": False}
    blocked_params: list[str] = []
    fixed_model: str | None = None

    async with httpx.AsyncClient(timeout=httpx.Timeout(30)) as client:
        for _attempt in range(8):
            try:
                resp = await client.post(endpoint, json=payload, headers=headers)
            except httpx.HTTPError as e:
                return {"ok": False, "issue": "connection", "detail": str(e)}

            if resp.status_code == 200:
                data = resp.json()
                # OpenAI can embed errors in a 200 body.
                if (not is_anthropic
                        and isinstance(data, dict)
                        and "error" in data
                        and "choices" not in data):
                    err = data["error"]
                    msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
                    return {"ok": False, "issue": "server_error", "detail": msg[:300]}
                result = {"ok": True}
                if fixed_model:
                    result["fixed_model"] = fixed_model
                if blocked_params:
                    result["blocked_params"] = blocked_params
                return result

            if resp.status_code not in (400, 404):
                return {"ok": False, "issue": "http_error", "detail": f"{resp.status_code}: {resp.text[:300]}"}

            error_text = resp.text[:500]
            error_lower = error_text.lower()

            # Invalid model ID (both providers).
            if ("invalid model" in error_lower
                    or "not_found" in error_lower
                    or "could not resolve" in error_lower):
                if "/" in model:
                    model = model.split("/", 1)[1]
                    payload["model"] = model
                    fixed_model = model
                    continue
                return {"ok": False, "issue": "invalid_model", "detail": error_text[:300]}

            # Rejected parameter (any provider).
            if (
                "unknown parameter" in error_lower
                or "unsupported parameter" in error_lower
                or "unsupported value" in error_lower
                or "deprecated" in error_lower
                or "not supported" in error_lower
            ):
                m = _BAD_PARAM_RE.search(error_text)
                if not m:
                    m = _BACKTICK_PARAM_RE.search(error_text)
                if m:
                    bad = m.group(1)
                    if bad in _ESSENTIAL_PARAMS:
                        return {"ok": False, "issue": "param_error", "detail": error_text[:300]}
                    alias = _PARAM_ALIASES.get(bad)
                    if alias and bad in payload:
                        payload[alias] = payload.pop(bad)
                        blocked_params.append(f"{bad}->{alias}")
                        continue
                    if bad in payload:
                        payload.pop(bad)
                        blocked_params.append(bad)
                        continue
                return {"ok": False, "issue": "param_error", "detail": error_text[:300]}

            return {"ok": False, "issue": "http_error", "detail": f"{resp.status_code}: {error_text[:300]}"}

    return result


def _run_probe(config: Config, config_path: Path, env_path: Path, io: WizardIO) -> None:
    """Run the API probe and report / apply fixes."""
    if config.provider.kind == "mock":
        return

    # Reload .env so the key written by _write_env_stub is available.
    from dotenv import load_dotenv
    load_dotenv(env_path, override=True)

    io.say("")
    io.say("Running a quick connection test...")

    try:
        result = asyncio.run(_probe_api(config))
    except Exception as e:
        io.say(f"Connection test skipped (could not reach server: {e})")
        return

    if result["ok"]:
        changes: list[str] = []

        if result.get("fixed_model"):
            config.provider.model = result["fixed_model"]
            changes.append(f"model → '{result['fixed_model']}' (prefix stripped for direct API)")

        if result.get("blocked_params"):
            # Remove or rename params in the default model_params.
            mp_dict = config.model_params.get("default")
            for p in result["blocked_params"]:
                if "->" in p:
                    old, new = p.split("->", 1)
                    changes.append(f"renamed '{old}' to '{new}' for this provider")
                else:
                    changes.append(f"removed unsupported parameter '{p}' from defaults")
                    if mp_dict:
                        dump = mp_dict.model_dump()
                        dump.pop(p, None)
                        from elifelse.config import ModelParams
                        config.model_params["default"] = ModelParams(**dump)
                        mp_dict = config.model_params["default"]

        if changes:
            # Re-write config.yaml with fixes applied.
            config = Config.model_validate(config.model_dump())
            config_yaml = (
                "# Generated by 'elifelse init'. Safe to edit by hand.\n"
                "# Every key is documented with comments in config.example.yaml.\n"
                + yaml.safe_dump(config.model_dump(), sort_keys=False, allow_unicode=True)
            )
            config_path.write_text(config_yaml, encoding="utf-8")
            io.say("Connection test passed! Auto-applied fixes to config.yaml:")
            for c in changes:
                io.say(f"  - {c}")
        else:
            io.say("Connection test passed!")
    else:
        issue = result.get("issue", "unknown")
        detail = result.get("detail", "")
        if issue == "api_key":
            io.say("Connection test skipped (API key not set yet).")
            io.say("After adding your key to .env, run 'elifelse run' to verify.")
        elif issue == "connection":
            io.say(f"Could not reach the server: {detail}")
            io.say("Make sure your model server is running and the URL is correct.")
        elif issue == "invalid_model":
            io.say(f"The API rejected the model name: {detail}")
            io.say("Check the model identifier in config.yaml and try again.")
        else:
            io.say(f"Connection test failed ({issue}): {detail}")
            io.say("Check your config.yaml settings and try 'elifelse run'.")


def _write_env_stub(env_path: Path, var_name: str, io: WizardIO) -> None:
    existing = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    if var_name in existing:
        io.say(f"{env_path} already has {var_name} set.")
        return
    key = io.text("Paste your API key (will be stored in .env, never in config.yaml)")
    if not key:
        io.say(f"No key entered. Add it later to {env_path} as: {var_name}=your-key")
        key = "PASTE-YOUR-API-KEY-HERE"
    with env_path.open("a", encoding="utf-8") as f:
        if existing and not existing.endswith("\n"):
            f.write("\n")
        f.write(f"{var_name}={key}\n")
    if key == "PASTE-YOUR-API-KEY-HERE":
        io.say(f"wrote {env_path} — open it and replace the placeholder with your key")
    else:
        io.say(f"wrote {env_path}")


def run_wizard(base_dir: Path | str = ".", ask: AskFn = input,
               say: Callable[[str], None] = print_system) -> int:
    base = Path(base_dir)
    io = WizardIO(ask, say)
    config_path = base / "config.yaml"
    persona_path = base / "persona.yaml"

    io.say("Eli Felse setup — a few questions, then you're running.")
    io.say("(Press Enter to accept the suggested default.)")
    io.say("")

    if config_path.exists() and not io.yesno(
        f"{config_path} already exists. Overwrite it?", default=False
    ):
        io.say("left everything as it was; nothing written")
        return 1

    config = Config()
    config.developer_name = io.text(
        "Your name (how the agent refers to you)", default="Developer"
    )
    config.provider = _ask_provider(io)

    io.say("")
    io.say("Day cycle: the agent keeps human hours — it goes to bed, sleeps (no API")
    io.say("calls at all), and wakes up on schedule. Recommended for paid APIs too.")
    config.day_cycle.enabled = io.yesno("Enable the day cycle?", default=True)
    if config.day_cycle.enabled:
        config.day_cycle.bedtime = io.hhmm("Bedtime", default="22:00")
        config.day_cycle.wake_time = io.hhmm("Wake time", default="08:00")

    persona: Persona | None = None
    if persona_path.exists():
        if io.yesno(f"{persona_path} already exists. Keep it?", default=True):
            io.say("keeping the existing persona")
        else:
            persona = _ask_persona(io, developer_name=config.developer_name)
    else:
        persona = _ask_persona(io, developer_name=config.developer_name)

    # Validate through the runtime models before anything touches disk.
    config = Config.model_validate(config.model_dump())
    config_yaml = (
        "# Generated by 'elifelse init'. Safe to edit by hand.\n"
        "# Every key is documented with comments in config.example.yaml.\n"
        + yaml.safe_dump(config.model_dump(), sort_keys=False, allow_unicode=True)
    )
    config_path.write_text(config_yaml, encoding="utf-8")
    io.say(f"wrote {config_path}")

    if persona is not None:
        persona = Persona.model_validate(persona.model_dump())
        persona_yaml = (
            "# Generated by 'elifelse init'. Safe to edit by hand.\n"
            "# See persona.example.yaml for the full commented version.\n"
            + yaml.safe_dump(persona.model_dump(), sort_keys=False, allow_unicode=True)
        )
        persona_path.write_text(persona_yaml, encoding="utf-8")
        io.say(f"wrote {persona_path}")

    if config.provider.api_key_env:
        _write_env_stub(base / ".env", config.provider.api_key_env, io)

    # Run a quick API probe to catch config issues early.
    _run_probe(config, config_path, base / ".env", io)

    io.say("")
    io.say("Done. Start the agent with:  elifelse run")
    if config.provider.kind == "mock":
        io.say("(mock demo: elifelse run --provider mock --max-iterations 3)")
    io.say("While it runs: /pause /resume /stop /help — or just type to chat.")
    return 0
