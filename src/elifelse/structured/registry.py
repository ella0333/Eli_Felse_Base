"""Schemas stay plain JSON-schema dicts — sent verbatim as response_format.json_schema.

The registry holds the core schemas, builds dynamic menu enums, and supports
"schema decorators": a module can register a function that adds a field to every
schema (the generalized streaming pattern, where a tts_chat field is added to
everything while a stream is live).
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

Schema = dict[str, Any]


def menu_schema(options: list[str]) -> Schema:
    """A thinking field plus a choice locked to exactly these options."""
    return {
        "type": "object",
        "properties": {
            "thinking": {"type": "string"},
            "choice": {"type": "string", "enum": list(options)},
        },
        "required": ["thinking", "choice"],
        "additionalProperties": False,
    }


def freetext_schema(field: str = "response", with_return: bool = False) -> Schema:
    """A thinking field plus one free-text content field (display-or-store only)."""
    props: dict[str, Any] = {
        "thinking": {"type": "string"},
        field: {"type": "string"},
    }
    required = ["thinking", field]
    if with_return:
        props["return_to_menu"] = {"type": "boolean"}
        required.append("return_to_menu")
    return {
        "type": "object",
        "properties": props,
        "required": required,
        "additionalProperties": False,
    }


CORE_SCHEMAS: dict[str, Schema] = {
    "bedtime_menu": menu_schema(["sleep", "stay_up"]),
    "chat_response": {
        "type": "object",
        "properties": {
            "thinking": {"type": "string"},
            "response": {"type": "string"},
            "return_to_menu": {"type": "boolean"},
        },
        "required": ["thinking", "response", "return_to_menu"],
        "additionalProperties": False,
    },
    "journal_entry": freetext_schema("entry"),
    "ponder_response": {
        "type": "object",
        "properties": {
            "thinking": {"type": "string"},
            "new_goals": {"type": "array", "items": {"type": "string"}},
            "return_to_menu": {"type": "boolean"},
        },
        "required": ["thinking", "new_goals", "return_to_menu"],
        "additionalProperties": False,
    },
    "game_command": {
        "type": "object",
        "properties": {
            "thinking": {"type": "string"},
            "command": {"type": "string"},
            "return_to_menu": {"type": "boolean"},
        },
        "required": ["thinking", "command", "return_to_menu"],
        "additionalProperties": False,
    },
    "survey_simple": {
        "type": "object",
        "properties": {
            "thinking": {"type": "string"},
            "emotion": {"type": "string", "description": "A single word."},
        },
        "required": ["thinking", "emotion"],
        "additionalProperties": False,
    },
    "survey_chat": {
        "type": "object",
        "properties": {
            "thinking": {"type": "string"},
            "emotion": {"type": "string", "description": "A single word."},
            "feeling": {
                "type": "string",
                "enum": ["love", "like", "slightly like", "slightly dislike", "dislike", "hate"],
            },
        },
        "required": ["thinking", "emotion", "feeling"],
        "additionalProperties": False,
    },
    "nap_interrupted": {
        "type": "object",
        "properties": {
            "thinking": {"type": "string"},
            "choice": {"type": "string", "enum": ["wake_up", "keep_sleeping"]},
        },
        "required": ["thinking", "choice"],
        "additionalProperties": False,
    },
    # Background extraction: one verdict per message in the batch.
    "extraction_batch": {
        "type": "object",
        "properties": {
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "message_index": {"type": "integer"},
                        "is_fact": {"type": "boolean"},
                        "fact_summary": {"type": "string"},
                        "is_memory": {"type": "boolean"},
                        "memory_summary": {"type": "string"},
                        "keywords": {"type": "array", "items": {"type": "string"}},
                        "is_goal_related": {"type": "boolean"},
                    },
                    "required": [
                        "message_index", "is_fact", "fact_summary",
                        "is_memory", "memory_summary", "keywords", "is_goal_related",
                    ],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["results"],
        "additionalProperties": False,
    },
    "fact_consolidation": {
        "type": "object",
        "properties": {
            "facts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["keep", "update", "remove"]},
                        "fact": {"type": "string"},
                    },
                    "required": ["action", "fact"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["facts"],
        "additionalProperties": False,
    },
    "goal_consolidation": {
        "type": "object",
        "properties": {
            "goals": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["keep", "accomplished", "remove"]},
                        "goal": {"type": "string"},
                    },
                    "required": ["action", "goal"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["goals"],
        "additionalProperties": False,
    },
}


class SchemaRegistry:
    """Core + module schemas, dynamic menus, and schema decorators."""

    def __init__(self) -> None:
        self._schemas: dict[str, Schema] = copy.deepcopy(CORE_SCHEMAS)
        self._decorators: dict[str, Callable[[Schema], Schema]] = {}
        self._active_decorators: list[str] = []

    def register(self, name: str, schema: Schema) -> None:
        self._schemas[name] = schema

    def get(self, name: str) -> Schema:
        if name not in self._schemas:
            raise KeyError(f"Unknown schema '{name}'. Registered: {sorted(self._schemas)}")
        return self.finalize(self._schemas[name])

    def menu(self, options: list[str]) -> Schema:
        return self.finalize(menu_schema(options))

    def freetext(self, field: str = "response", with_return: bool = False) -> Schema:
        return self.finalize(freetext_schema(field, with_return))

    # ~~~ decorators ~~~
    def add_decorator(self, name: str, fn: Callable[[Schema], Schema]) -> None:
        """Register a decorator that transforms schemas when activated."""
        self._decorators[name] = fn

    def activate_decorator(self, name: str) -> None:
        if name not in self._decorators:
            raise KeyError(f"Unknown schema decorator '{name}'")
        if name not in self._active_decorators:
            self._active_decorators.append(name)

    def deactivate_decorator(self, name: str) -> None:
        if name in self._active_decorators:
            self._active_decorators.remove(name)

    def finalize(self, schema: Schema) -> Schema:
        """Apply all active decorators to a deep copy of the schema."""
        result = copy.deepcopy(schema)
        for name in self._active_decorators:
            result = self._decorators[name](result)
        return result
