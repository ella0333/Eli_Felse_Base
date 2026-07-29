"""The ctx API — making the safe path the easiest path.

Modules get typed, PRE-VALIDATED results instead of raw LLM responses. All
parsing, retries, enum checking and placeholder rejection happen inside the
framework; a module never needs to touch raw model output.

The module contract:
    LLM output may be (1) displayed, (2) stored, or (3) passed to a constrained
    parser — an enum, a pattern, a game engine, a sandbox. It may NEVER reach a
    shell, an eval, a filesystem path, or an outbound request.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from elifelse.loop.menus import build_choice_menu
from elifelse.providers.base import GenerationError
from elifelse.structured.registry import freetext_schema, menu_schema

if TYPE_CHECKING:
    from elifelse.activities.base import Activity
    from elifelse.app import App


class ActivityContext:
    """Everything an activity is allowed to touch. Modules only ever see this,
    never the App itself."""

    def __init__(self, app: App, activity: Activity) -> None:
        self.app = app
        self.activity = activity

    # ~~~ identity / config ~~~
    @property
    def persona(self):
        return self.app.persona

    @property
    def developer_name(self) -> str:
        return self.app.config.developer_name

    @property
    def config(self) -> dict[str, Any]:
        """This activity's own section from config.yaml (activities.<key>)."""
        return self.app.config.activities.get(self.activity.key, {})

    @property
    def data_dir(self) -> Path:
        """This activity's own storage folder under data/."""
        return self.app.paths.activity_dir(self.activity.key)

    @property
    def channels(self) -> dict[str, Any]:
        return self.app.channels

    @property
    def limits(self):
        return self.app.limits

    @property
    def schemas(self):
        return self.app.schemas

    def set_status(self, text: str, details: dict[str, Any] | None = None) -> None:
        self.app.status.set_activity(text, details)

    # ~~~ the safe LLM surface ~~~
    async def choose(
        self,
        prompt: str,
        options: list[str],
        labels: list[str] | None = None,
        footer: str = "",
    ) -> str:
        """Ask the agent to pick one of `options`. Returns one validated
        option. The module never sees the JSON.

        The choice is put to the model as a lettered menu, exactly like the
        main menu: the prompt shows "A) label" lines and the schema enum is
        the letters, so the only thing the model can answer with is a letter.
        Pass `labels` when the option value and the text to show differ (a
        game key vs. its name and description); `footer` adds a closing line
        under the options.
        """
        shown = labels if labels is not None else options
        menu = build_choice_menu(prompt, options, labels=shown, footer=footer)
        # Always print the menu so the terminal reflects what the model sees.
        print(f"\n{menu.text}")
        schema = self.app.schemas.finalize(menu_schema(menu.letters))
        result = await self.app.provider.generate(menu.text, schema=schema)
        letter = str(result.get("choice", "")).strip().upper()
        if "error" in result or letter not in menu.mapping:
            raise GenerationError(f"choose() failed: {result.get('error', 'no valid choice')}")
        if result.get("thinking"):
            print(f"\nThinking: {result['thinking']}")
        print(f"Choice: {letter} — {shown[menu.letters.index(letter)]}")
        return menu.mapping[letter]

    async def freetext(self, prompt: str, field: str = "response") -> str:
        """Free text from the agent. DISPLAY-OR-STORE ONLY."""
        schema = self.app.schemas.finalize(freetext_schema(field))
        result = await self.app.provider.generate(prompt, schema=schema)
        if "error" in result or not result.get(field):
            raise GenerationError(f"freetext() failed: {result.get('error', 'empty')}")
        text = str(result[field])
        if result.get("thinking"):
            print(f"\nThinking: {result['thinking']}")
        print(f"\n{self.app.persona.name}: {text}")
        return text

    async def chat(self, prompt: str | None = None) -> tuple[str, bool]:
        """One chat turn: returns (response_text, wants_to_return_to_menu)."""
        schema = self.app.schemas.get("chat_response")
        result = await self.app.provider.generate(prompt, schema=schema)
        if "error" in result or not result.get("response"):
            raise GenerationError(f"chat() failed: {result.get('error', 'empty')}")
        if result.get("thinking"):
            print(f"\nThinking: {result['thinking']}")
        return str(result["response"]), bool(result.get("return_to_menu", False))

    async def constrained(self, prompt: str, pattern: str, max_attempts: int = 5) -> str:
        """Free text validated against a regex BEFORE the module gets it —
        for game moves and parser commands (the chess/frotz case)."""
        compiled = re.compile(pattern)
        attempt_prompt = prompt
        for _ in range(max_attempts):
            schema = self.app.schemas.finalize(freetext_schema("command"))
            result = await self.app.provider.generate(attempt_prompt, schema=schema)
            command = str(result.get("command", "")).strip()
            if "error" not in result and compiled.fullmatch(command):
                return command
            attempt_prompt = (
                f"That wasn't a valid input (it must match the required format). {prompt}"
            )
        raise GenerationError(f"constrained() got no input matching {pattern!r}")

    async def generate(self, prompt: str | None, schema: dict[str, Any]) -> dict[str, Any]:
        """Power path: any registered/custom schema, still fully validated.
        Raises instead of returning an error dict, so modules can't miss it."""
        result = await self.app.provider.generate(prompt, schema=self.app.schemas.finalize(schema))
        if "error" in result:
            raise GenerationError(str(result["error"]))
        return result

    # ~~~ memory ~~~
    async def recall(self, query: str, source: str | None = None) -> list[str]:
        """Relevant memories for a query (two-tier: source-specific, then global)."""
        if self.app.memory is None:
            return []
        return await self.app.memory.recall(query, source or self.activity.key)

    def remember(self, role: str, content: str, subject: str = "") -> None:
        """Buffer a message for background memory extraction (batched)."""
        if self.app.memory is None:
            return
        self.app.memory.push_message(
            session_key=f"{self.activity.key}_{subject}" if subject else self.activity.key,
            role=role,
            content=content,
            source=subject or self.activity.key,
            activity_type=self.activity.key,
            rules=self.activity.memory_rules,
        )

    def remember_game(self, role: str, content: str, subject: str = "", save_state: str = "") -> None:
        """Buffer a game message for 3-msg-merge extraction (no classifier)."""
        if self.app.memory is None:
            return
        self.app.memory.push_game_message(
            session_key=f"{self.activity.key}_{subject}" if subject else self.activity.key,
            role=role,
            content=content,
            source=subject or self.activity.key,
            activity_type=self.activity.key,
            save_state=save_state,
        )
