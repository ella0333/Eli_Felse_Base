"""OpenAI-compatible chat-completions provider (also speaks Anthropic).

Works with LM Studio, Ollama, llama.cpp server, vLLM, OpenRouter, OpenAI,
Anthropic, and any other endpoint speaking the /v1/chat/completions dialect.
Anthropic's Messages API is auto-detected by host and handled transparently:
system messages move to the top-level ``system`` field, structured output uses
forced tool_use, and responses are parsed from ``content`` blocks.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

import httpx

from elifelse.config import Config, ConfigError
from elifelse.providers.base import CompletionResult, Provider
from elifelse.providers.budget import TokenBudget
from elifelse.providers.lmstudio_loader import lms_available, lms_load_models
from elifelse.textutils import print_system

# Hosts that always require an API key.
_PAID_HOSTS = {"api.openai.com", "openrouter.ai", "api.anthropic.com"}

# Hosts that speak the Anthropic Messages API instead of OpenAI chat completions.
_ANTHROPIC_HOSTS = {"api.anthropic.com"}

# Regexes to extract the offending parameter from provider error messages.
# Pattern 1 (OpenAI): "Unknown parameter: 'X'", "Unsupported value: 'X' ..."
_BAD_PARAM_RE = re.compile(
    r"[Uu]n(?:known|supported) (?:parameter|value):?\s*'?\"?(\w+)"
)
# Pattern 2 (Anthropic): "`temperature` is deprecated for this model"
_BACKTICK_PARAM_RE = re.compile(r"`(\w+)`")

# Parameters that have a known alternate name on certain providers.
_PARAM_ALIASES: dict[str, str] = {
    "max_tokens": "max_completion_tokens",  # OpenAI newer/reasoning models
}

# Never remove these from the payload, even on error.
_ESSENTIAL_PARAMS = {"model", "messages", "stream"}

# Maximum number of parameter-fix retries per _complete call.
_MAX_PARAM_RETRIES = 6


class OpenAICompatProvider(Provider):
    def __init__(self, config: Config, budget: TokenBudget | None = None) -> None:
        super().__init__(config, budget)
        url = self.pconf.base_url.rstrip("/")
        # Normalize: ensure the URL ends with /v1 so we always hit /v1/chat/completions.
        # Handles both "http://localhost:1234" and "http://localhost:1234/v1".
        if not url.endswith("/v1"):
            url += "/v1"
        self.base_url = url
        self._client: httpx.AsyncClient | None = None
        # Parameters the remote API has rejected (cached across calls).
        self._blocked_params: set[str] = set()
        # Parameters renamed for this provider (e.g. max_tokens -> max_completion_tokens).
        self._param_renames: dict[str, str] = {}
        # Model name already stripped of prefix once (cached across calls).
        self._model_stripped: dict[str, str] = {}
        host = (urlparse(self.base_url).hostname or "").lower()
        self._is_anthropic = any(host == h or host.endswith("." + h) for h in _ANTHROPIC_HOSTS)
        # Auto-enable /no_think for Qwen models (they dump JSON into
        # reasoning_content instead of content when thinking mode is on).
        if "qwen" in self.pconf.model.lower() and not self.pconf.quirks.no_think_suffix:
            self.pconf.quirks.no_think_suffix = True
            print_system("Qwen model detected — auto-enabled /no_think suffix")
        self._check_cloud_auth()

    def _check_cloud_auth(self) -> None:
        """Fail fast when a known cloud API has no key configured."""
        host = (urlparse(self.base_url).hostname or "").lower()
        if any(host == h or host.endswith("." + h) for h in _PAID_HOSTS):
            if not self.pconf.api_key_env:
                raise ConfigError(
                    f"provider.base_url points to {host}, which requires an API key, "
                    f"but provider.api_key_env is empty. Set it to the name of the "
                    f"environment variable holding your key (e.g. OPENROUTER_API_KEY) "
                    f"and add the key to your .env file."
                )

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        key = self.pconf.api_key()
        if self._is_anthropic:
            headers["anthropic-version"] = "2023-06-01"
            if key:
                headers["x-api-key"] = key
        elif key:
            headers["Authorization"] = f"Bearer {key}"
        return headers

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(self.pconf.request_timeout))
        return self._client

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    async def ensure_loaded(self) -> None:
        """Optional LM Studio add-on: load the model with the right context length
        via the `lms` CLI. Only runs when enabled AND the CLI exists on PATH."""
        if not self.pconf.lmstudio_loader:
            return
        # Guard: skip if the URL points to a non-LM-Studio server (e.g. Ollama).
        host = (urlparse(self.base_url).hostname or "").lower()
        port = urlparse(self.base_url).port
        if port and port != 1234 and host in ("localhost", "127.0.0.1"):
            print_system(
                f"lmstudio_loader is enabled but server is on port {port} "
                f"(LM Studio uses 1234). Skipping auto-load."
            )
            return
        if not lms_available():
            return
        await lms_load_models(
            model=self.pconf.model,
            context_tokens=self.pconf.max_context_tokens,
            utility_model=self.pconf.utility_model or None,
        )

    def _apply_renames(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Rename any parameters that this provider uses a different name for."""
        for old, new in self._param_renames.items():
            if old in payload:
                payload[new] = payload.pop(old)
        return payload

    def _build_payload(
        self, model: str, messages: list[dict[str, Any]],
        schema: dict[str, Any] | None, raw: bool,
    ) -> dict[str, Any]:
        """Assemble the request payload, skipping any previously rejected params."""
        mp = self.config.params_for(model)
        # Start with all params; blocked ones are skipped.
        candidates: dict[str, Any] = {
            "temperature": mp.temperature_raw if raw else mp.temperature,
            "top_p": mp.top_p,
            "max_tokens": mp.max_tokens_raw if raw else mp.max_tokens,
            "repeat_penalty": mp.repeat_penalty,
        }
        if mp.top_k:
            candidates["top_k"] = mp.top_k
        if mp.chat_template_kwargs:
            candidates["chat_template_kwargs"] = mp.chat_template_kwargs

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
        }
        for key, value in candidates.items():
            if key not in self._blocked_params:
                payload[key] = value
        if schema:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "response", "strict": True, "schema": schema},
            }
        return self._apply_renames(payload)

    def _build_anthropic_payload(
        self, model: str, messages: list[dict[str, Any]],
        schema: dict[str, Any] | None, raw: bool,
    ) -> dict[str, Any]:
        """Assemble a payload for the Anthropic Messages API."""
        mp = self.config.params_for(model)

        # Separate system messages from chat messages.
        system_parts: list[str] = []
        chat_msgs: list[dict[str, Any]] = []
        for msg in messages:
            if msg["role"] == "system":
                content = msg["content"]
                if isinstance(content, str):
                    system_parts.append(content)
            else:
                # Strip 'name' field (Anthropic doesn't support it).
                chat_msgs.append({"role": msg["role"], "content": msg["content"]})

        # Merge consecutive same-role messages (Anthropic requires alternation).
        merged: list[dict[str, Any]] = []
        for msg in chat_msgs:
            if merged and merged[-1]["role"] == msg["role"]:
                prev = merged[-1]["content"]
                cur = msg["content"]
                if isinstance(prev, str) and isinstance(cur, str):
                    merged[-1]["content"] = prev + "\n\n" + cur
                else:
                    merged[-1]["content"] = str(prev) + "\n\n" + str(cur)
            else:
                merged.append(dict(msg))

        # Anthropic requires messages to start with 'user'.
        if merged and merged[0]["role"] != "user":
            merged.insert(0, {"role": "user", "content": "(continue)"})
        if not merged:
            merged.append({"role": "user", "content": "(continue)"})

        payload: dict[str, Any] = {
            "model": model,
            "messages": merged,
            "max_tokens": mp.max_tokens_raw if raw else mp.max_tokens,
            "stream": False,
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)

        # Sampling params (skip any previously rejected by this provider).
        if "temperature" not in self._blocked_params:
            payload["temperature"] = mp.temperature_raw if raw else mp.temperature
        if "top_p" not in self._blocked_params and mp.top_p:
            payload["top_p"] = mp.top_p
        if "top_k" not in self._blocked_params and mp.top_k:
            payload["top_k"] = mp.top_k

        # Structured output via forced tool use.
        if schema:
            payload["tools"] = [{
                "name": "response",
                "description": "Respond with the required structured data.",
                "input_schema": schema,
            }]
            payload["tool_choice"] = {"type": "tool", "name": "response"}

        return payload

    def _strip_model_prefix(self, model: str) -> str | None:
        """Return the model name without a publisher prefix, or None if there's
        nothing to strip (e.g. 'gpt-5.6-luna' stays the same, but
        'openai/gpt-5.6-luna' becomes 'gpt-5.6-luna').

        Direct provider APIs (OpenAI, Anthropic) use the bare model name.
        Aggregators (OpenRouter) use the 'publisher/model' format.
        """
        if "/" not in model:
            return None
        stripped = model.split("/", 1)[1]
        if stripped == model:
            return None
        return stripped

    async def _send_request(
        self, payload: dict[str, Any],
    ) -> tuple[httpx.Response | None, str | None]:
        """POST to the provider endpoint. Returns (response, error_string)."""
        endpoint = "messages" if self._is_anthropic else "chat/completions"
        try:
            resp = await self._get_client().post(
                f"{self.base_url}/{endpoint}", json=payload, headers=self._headers()
            )
            return resp, None
        except httpx.HTTPError as e:
            return None, f"connection_error: {e}"

    def _parse_response(
        self, resp: httpx.Response, messages: list[dict[str, Any]],
    ) -> CompletionResult:
        """Turn a successful HTTP response into a CompletionResult."""
        if resp.status_code != 200:
            return CompletionResult(text=None, error=f"{resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        if isinstance(data, dict) and "error" in data and "choices" not in data:
            err = data["error"]
            msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            return CompletionResult(text=None, error=f"server_error: {msg[:300]}")
        try:
            msg = data["choices"][0]["message"]
            content = msg.get("content") or ""
            # Qwen thinking mode: actual answer lands in reasoning_content
            # while content is empty.  Fall back to reasoning_content.
            if not content and msg.get("reasoning_content"):
                content = msg["reasoning_content"]
        except (KeyError, IndexError, TypeError):
            return CompletionResult(text=None, error=f"unexpected_response_shape: {str(data)[:200]}")
        tokens = 0
        usage = data.get("usage") or {}
        if isinstance(usage, dict):
            tokens = int(usage.get("total_tokens") or 0)
        if not tokens:
            est_prompt = sum(
                len(m["content"]) if isinstance(m["content"], str) else 1000 for m in messages
            )
            tokens = (est_prompt + len(content or "")) // 4
        return CompletionResult(text=content, tokens=tokens)

    def _parse_anthropic_response(
        self, resp: httpx.Response, messages: list[dict[str, Any]],
    ) -> CompletionResult:
        """Turn an Anthropic Messages API response into a CompletionResult."""
        if resp.status_code != 200:
            return CompletionResult(text=None, error=f"{resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        # Anthropic error envelope: {"type": "error", "error": {"message": ...}}
        if isinstance(data, dict) and data.get("type") == "error":
            err = data.get("error", {})
            msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            return CompletionResult(text=None, error=f"server_error: {msg[:300]}")
        # Extract text from content blocks.
        text = None
        for block in data.get("content", []):
            if block.get("type") == "tool_use":
                text = json.dumps(block.get("input", {}))
                break
            if block.get("type") == "text":
                text = block.get("text", "")
                break
        if text is None:
            return CompletionResult(text=None, error=f"unexpected_response_shape: {str(data)[:200]}")
        # Token usage.
        tokens = 0
        usage = data.get("usage") or {}
        if isinstance(usage, dict):
            tokens = int(usage.get("input_tokens") or 0) + int(usage.get("output_tokens") or 0)
        if not tokens:
            est_prompt = sum(
                len(m["content"]) if isinstance(m["content"], str) else 1000 for m in messages
            )
            tokens = (est_prompt + len(text or "")) // 4
        return CompletionResult(text=text, tokens=tokens)

    def _extract_error_text(self, resp: httpx.Response) -> str:
        """Pull a readable error string from any response."""
        if resp.status_code != 200:
            return resp.text[:500]
        try:
            body = resp.json()
            if isinstance(body, dict) and "error" in body and "choices" not in body:
                err = body["error"]
                return err.get("message", str(err)) if isinstance(err, dict) else str(err)
        except Exception:
            pass
        return ""

    def _try_fix_param(self, error_text: str, payload: dict[str, Any]) -> bool:
        """Attempt to fix a parameter error in-place. Returns True if fixed."""
        m = _BAD_PARAM_RE.search(error_text)
        if not m:
            m = _BACKTICK_PARAM_RE.search(error_text)
        if not m:
            return False
        bad_param = m.group(1)
        if bad_param in _ESSENTIAL_PARAMS:
            return False

        # Try renaming to a known alias first.
        alias = _PARAM_ALIASES.get(bad_param)
        if alias and bad_param not in self._param_renames:
            self._param_renames[bad_param] = alias
            if bad_param in payload:
                payload[alias] = payload.pop(bad_param)
            print_system(f"Parameter '{bad_param}' not supported; using '{alias}' instead")
            return True

        # Otherwise remove it entirely (API will use its default).
        if bad_param not in self._blocked_params:
            self._blocked_params.add(bad_param)
            payload.pop(bad_param, None)
            # Also remove the alias form if present.
            for orig, renamed in self._param_renames.items():
                if orig == bad_param:
                    payload.pop(renamed, None)
            print_system(f"Parameter '{bad_param}' not supported; removed")
            return True

        return False

    async def _complete(
        self,
        messages: list[dict[str, Any]],
        schema: dict[str, Any] | None,
        model: str,
        raw: bool,
    ) -> CompletionResult:
        # Use a previously resolved stripped model name if available.
        effective_model = self._model_stripped.get(model, model)
        if self._is_anthropic:
            payload = self._build_anthropic_payload(effective_model, messages, schema, raw)
            parse = self._parse_anthropic_response
        else:
            payload = self._build_payload(effective_model, messages, schema, raw)
            parse = self._parse_response

        for _attempt in range(_MAX_PARAM_RETRIES):
            resp, conn_err = await self._send_request(payload)
            if conn_err:
                return CompletionResult(text=None, error=conn_err)

            error_text = self._extract_error_text(resp)

            # Success — no error to fix.
            if resp.status_code == 200 and not error_text:
                return parse(resp, messages)

            if resp.status_code not in (400, 404) or not error_text:
                break

            error_lower = error_text.lower()

            # Auto-fix: invalid model ID — strip publisher prefix.
            if ("invalid model" in error_lower
                    or "not_found" in error_lower
                    or "could not resolve" in error_lower):
                stripped = self._strip_model_prefix(payload.get("model", ""))
                if stripped:
                    print_system(
                        f"Model '{payload['model']}' rejected; retrying as '{stripped}'"
                    )
                    self._model_stripped[model] = stripped
                    payload["model"] = stripped
                    continue
                break  # No prefix to strip; nothing we can fix.

            # Auto-fix: rejected parameter (any provider).
            if (
                "unknown parameter" in error_lower
                or "unsupported parameter" in error_lower
                or "unsupported value" in error_lower
                or "deprecated" in error_lower
                or "not supported" in error_lower
            ):
                if self._try_fix_param(error_text, payload):
                    continue
                break  # Could not identify or fix the parameter.

            break  # Unrecognized error; stop retrying.

        return parse(resp, messages)
