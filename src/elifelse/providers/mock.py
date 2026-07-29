"""MockProvider — scripted playback, no model needed.

Powers the whole test suite and CI, and lets module authors drive their entire
activity flow (menus, schemas, isolation, summaries) in seconds with no model
loaded and no API cost.

Two modes, combinable:
- a script: a list of responses played back in order (dicts are JSON-encoded);
- auto mode (script exhausted or absent): synthesize a schema-valid response,
  picking `always_option` (0-based) from any enum field.
"""

from __future__ import annotations

import json
from typing import Any

from elifelse.config import Config
from elifelse.providers.base import CompletionResult, Provider


class MockProvider(Provider):
    def __init__(
        self,
        config: Config,
        script: list[dict[str, Any] | str] | None = None,
        always_option: int = 0,
        auto_fields: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(config)
        self.script: list[dict[str, Any] | str] = list(script or [])
        self.always_option = always_option
        self.auto_fields = auto_fields or {}
        self.calls: list[dict[str, Any]] = []  # for test assertions

        # Mock runs are always instant.
        async def _no_sleep(_seconds: float) -> None:
            return None

        self._sleep = _no_sleep

    def feed(self, *responses: dict[str, Any] | str) -> None:
        """Append more scripted responses."""
        self.script.extend(responses)

    async def _complete(
        self,
        messages: list[dict[str, Any]],
        schema: dict[str, Any] | None,
        model: str,
        raw: bool,
    ) -> CompletionResult:
        self.calls.append({"messages": messages, "schema": schema, "model": model, "raw": raw})
        if self.script:
            item = self.script.pop(0)
            text = json.dumps(item) if isinstance(item, dict) else item
            return CompletionResult(text=text, tokens=max(1, len(text) // 4))
        text = json.dumps(self._auto_response(schema)) if schema else "Mock response."
        return CompletionResult(text=text, tokens=max(1, len(text) // 4))

    def _auto_response(self, schema: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name, prop in schema.get("properties", {}).items():
            if name in self.auto_fields:
                out[name] = self.auto_fields[name]
            elif "enum" in prop:
                enum = prop["enum"]
                out[name] = enum[min(self.always_option, len(enum) - 1)]
            elif prop.get("type") == "string":
                out[name] = "Mock thinking." if name == "thinking" else f"Mock {name}."
            elif prop.get("type") == "boolean":
                out[name] = False
            elif prop.get("type") == "integer":
                out[name] = 0
            elif prop.get("type") == "number":
                out[name] = 0.0
            elif prop.get("type") == "array":
                out[name] = []
            else:
                out[name] = None
        return out
