"""The safety core: parse and validate model output against a JSON schema.

This is a PURE FUNCTION — no I/O, no retries (the provider owns the retry loop).
A response only ever reaches a caller if it passed every check here:

- JSON parses (with a regex-extraction fallback for chatty models)
- every required field is present
- content fields are non-empty and not "..." placeholders
- every enum field matches the allowed list EXACTLY — this is what makes the
  menu un-escapable

Anything else is rejected and the provider regenerates (up to 5 attempts).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from elifelse.textutils import clean_thinking, is_placeholder, strip_harmony_tags

# Required fields that must carry real content (not "" / "..."). These are the
# fields whose text is displayed or stored; enum fields are checked separately.
CONTENT_FIELDS = ("response", "command", "entry", "text", "note")

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


@dataclass
class ValidationResult:
    parsed: dict[str, Any] | None
    reason: str | None = None  # None = valid

    @property
    def ok(self) -> bool:
        return self.parsed is not None and self.reason is None


def parse_and_validate(content: str, schema: dict[str, Any] | None) -> ValidationResult:
    """Validate raw model output against a schema. Returns parsed dict or a reason."""
    if schema is None:
        # Unstructured call: just clean the text.
        return ValidationResult({"response": strip_harmony_tags(content)})

    parsed = _parse_json(content)
    if parsed is None:
        return ValidationResult(None, "malformed_json")
    if not isinstance(parsed, dict):
        return ValidationResult(None, "not_an_object")

    # Strip leaked formatting tags from all top-level string fields.
    for key, val in list(parsed.items()):
        if isinstance(val, str):
            parsed[key] = strip_harmony_tags(val)

    required = schema.get("required", [])
    missing = [f for f in required if f not in parsed]
    if missing:
        return ValidationResult(None, f"missing_fields:{','.join(missing)}")

    # Content fields must be substantive when required.
    for key in CONTENT_FIELDS:
        if key in required and parsed.get(key) is not None:
            if is_placeholder(str(parsed[key])):
                return ValidationResult(None, f"empty_content:{key}")

    # Enum fields must match the allowed list exactly.
    for field_name, field_schema in schema.get("properties", {}).items():
        if "enum" in field_schema and field_name in parsed:
            if parsed[field_name] not in field_schema["enum"]:
                return ValidationResult(
                    None,
                    f"enum_violation:{field_name}={parsed[field_name]!r}",
                )

    # Cleanup: strip mimicked "[Thinking: ...]" wrappers.
    if isinstance(parsed.get("thinking"), str):
        parsed["thinking"] = clean_thinking(parsed["thinking"])

    return ValidationResult(parsed)


def _parse_json(content: str) -> Any | None:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    # The model wrapped the JSON in prose — extract the object.
    match = _JSON_OBJECT_RE.search(content)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            return None
    return None
