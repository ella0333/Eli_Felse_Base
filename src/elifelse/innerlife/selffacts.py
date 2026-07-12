"""Self-facts — small persistent things the agent knows about itself
("I like rainy days", "I'm working through Moby-Dick"). They ride along in
the base prompt, so identity accretes across restarts."""

from __future__ import annotations

import json
from pathlib import Path

from elifelse.trackers.stats import atomic_write_json

MAX_SELF_FACTS = 15


class SelfFacts:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.facts: list[str] = []
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                self.facts = [str(f) for f in data.get("facts", [])]
            except (json.JSONDecodeError, OSError):
                pass

    def add(self, text: str) -> None:
        text = text.strip()
        if not text or text in self.facts:
            return
        self.facts.append(text)
        del self.facts[:-MAX_SELF_FACTS]  # oldest fall off past the cap
        atomic_write_json(self.path, {"facts": self.facts})

    def prompt_block(self) -> str:
        if not self.facts:
            return ""
        return "Things you know about yourself:\n" + "\n".join(f"- {f}" for f in self.facts)
