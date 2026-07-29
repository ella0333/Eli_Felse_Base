"""Adversarial validation tests: prove out-of-schema output can never pass."""

import json

from elifelse.structured.registry import menu_schema
from elifelse.structured.validation import parse_and_validate

MENU = menu_schema(["A", "B", "C"])


def test_valid_menu_choice_passes():
    r = parse_and_validate(json.dumps({"thinking": "hm", "choice": "B"}), MENU)
    assert r.ok
    assert r.parsed["choice"] == "B"


def test_out_of_enum_choice_rejected():
    r = parse_and_validate(json.dumps({"thinking": "hm", "choice": "Z"}), MENU)
    assert not r.ok
    assert "enum_violation" in r.reason


def test_injected_prose_choice_rejected():
    # Classic injection shape: the "choice" tries to smuggle an instruction.
    r = parse_and_validate(
        json.dumps({"thinking": "x", "choice": "A; rm -rf / #"}), MENU
    )
    assert not r.ok
    assert "enum_violation" in r.reason


def test_malformed_json_rejected():
    r = parse_and_validate("this is not json at all", MENU)
    assert not r.ok
    assert r.reason == "malformed_json"


def test_json_extracted_from_prose():
    raw = 'Sure! Here is my answer:\n{"thinking": "ok", "choice": "C"}\nHope that helps!'
    r = parse_and_validate(raw, MENU)
    assert r.ok
    assert r.parsed["choice"] == "C"


def test_missing_required_field_rejected():
    r = parse_and_validate(json.dumps({"thinking": "no choice here"}), MENU)
    assert not r.ok
    assert "missing_fields:choice" in r.reason


def test_placeholder_content_rejected():
    schema = {
        "type": "object",
        "properties": {"thinking": {"type": "string"}, "response": {"type": "string"}},
        "required": ["thinking", "response"],
        "additionalProperties": False,
    }
    for placeholder in ["...", "[...]", "(...)", "[...].", "", "   "]:
        r = parse_and_validate(json.dumps({"thinking": "t", "response": placeholder}), schema)
        assert not r.ok, f"placeholder {placeholder!r} should be rejected"
        assert "empty_content" in r.reason


def test_thinking_wrapper_stripped():
    r = parse_and_validate(
        json.dumps({"thinking": "[Thinking: [Thinking: nested]]", "choice": "A"}), MENU
    )
    assert r.ok
    assert r.parsed["thinking"] == "nested"


def test_harmony_tags_stripped():
    r = parse_and_validate(
        json.dumps({"thinking": "<|channel|>final<|message|>clean", "choice": "A"}), MENU
    )
    assert r.ok
    assert "<|" not in r.parsed["thinking"]


def test_non_object_rejected():
    r = parse_and_validate("[1, 2, 3]", MENU)
    assert not r.ok


def test_no_schema_returns_cleaned_text():
    r = parse_and_validate("plain text <|tag|> reply", None)
    assert r.ok
    assert "<|" not in r.parsed["response"]
