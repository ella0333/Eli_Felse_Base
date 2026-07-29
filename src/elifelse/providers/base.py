"""Provider interface + the context store.

The Provider owns the ONLY path between the framework and a model. All HTTP sits
behind one asyncio.Lock so background work (memory extraction, summaries) queues
behind the foreground loop instead of colliding with it.

`generate()` implements the validated retry loop ONCE, generically: pacing delay,
context management, parse -> validate -> regenerate (up to 5 attempts). Concrete
providers only implement `_complete()` (one raw model call).
"""

from __future__ import annotations

import asyncio
import copy
import random
import re
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from elifelse.config import Config
from elifelse.providers.budget import TokenBudget
from elifelse.structured.validation import parse_and_validate
from elifelse.textutils import print_system

MAX_GENERATE_ATTEMPTS = 5

# Which parsed field becomes the assistant turn stored in context.
_CONTEXT_CONTENT_KEYS = ("response", "command", "entry", "note")


class GenerationError(Exception):
    """Raised when the model could not produce a valid response. A caller can
    never receive an out-of-schema value — it receives this instead."""


@dataclass
class Snapshot:
    """A byte-identical copy of the context at a point in time."""

    messages: list[dict[str, Any]]
    timestamps: list[str]
    system_prompt: str


@dataclass
class CompletionResult:
    text: str | None
    error: str | None = None
    tokens: int = 0


class ContextStore:
    """A deque of user/assistant messages only.

    The system prompt is stored separately, always injected first, always the
    current one — activities swap it freely without polluting history. Every
    message gets a wall-clock timestamp appended plus a parallel ISO timestamp
    deque so the memory system knows the oldest surviving message.
    """

    def __init__(self, max_chars: int, agent_name: str = "") -> None:
        self.max_chars = max_chars
        self.agent_name = agent_name
        self.messages: deque[dict[str, Any]] = deque()
        self.timestamps: deque[str] = deque()
        self.system_prompt = ""

    def set_system_prompt(self, prompt: str) -> None:
        self.system_prompt = prompt

    def add(self, role: str, content: Any, image_placeholder: bool = False) -> None:
        """Add a user or assistant message. System messages are never stored here."""
        if role == "system":
            return
        now = datetime.now()
        if isinstance(content, str):
            if image_placeholder:
                content = content + "\n(image)"
            content = f"{content}\n[{now.strftime('%I:%M %p')}]"
        msg: dict[str, Any] = {"role": role, "content": content}
        if role == "assistant" and self.agent_name:
            # Sanitize for OpenAI's name pattern: ^[^\s<|\\/>]+
            safe_name = re.sub(r'[\s<|\\/>]+', '_', self.agent_name).strip('_')
            if safe_name:
                msg["name"] = safe_name
        self.messages.append(msg)
        self.timestamps.append(now.isoformat())
        self.trim()

    @staticmethod
    def _content_len(content: Any) -> int:
        if isinstance(content, str):
            return len(content)
        total = 0
        for part in content:
            if part.get("type") == "text":
                total += len(part.get("text", ""))
            else:
                total += 1000  # flat cost per non-text part
        return total

    def total_chars(self) -> int:
        return len(self.system_prompt) + sum(self._content_len(m["content"]) for m in self.messages)

    def trim(self) -> int:
        """Drop oldest messages from the FRONT until under budget.

        The system prompt is never trimmed; a minimum of 2 messages is kept.
        Returns the number of messages dropped.
        """
        total = self.total_chars()
        dropped = 0
        while total > self.max_chars and len(self.messages) > 2:
            removed = self.messages.popleft()
            if self.timestamps:
                self.timestamps.popleft()
            total -= self._content_len(removed["content"])
            dropped += 1
        if dropped:
            print_system(f"Context trimmed: {dropped} message{'s' if dropped != 1 else ''} dropped")
        return dropped

    def build_messages(self) -> list[dict[str, Any]]:
        """[system_prompt] + context. One system prompt, always current, always first."""
        messages: list[dict[str, Any]] = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        messages.extend(copy.deepcopy(list(self.messages)))
        return messages

    def snapshot(self) -> Snapshot:
        return Snapshot(
            messages=copy.deepcopy(list(self.messages)),
            timestamps=list(self.timestamps),
            system_prompt=self.system_prompt,
        )

    def restore(self, snap: Snapshot) -> None:
        self.messages = deque(copy.deepcopy(snap.messages))
        self.timestamps = deque(snap.timestamps)
        self.system_prompt = snap.system_prompt
        self.trim()

    def messages_since(self, snap: Snapshot) -> list[dict[str, Any]]:
        """Messages added after a snapshot was taken (for summaries/extraction)."""
        return list(self.messages)[len(snap.messages):]

    def oldest_timestamp(self) -> str | None:
        return self.timestamps[0] if self.timestamps else None

    def clear(self) -> None:
        self.messages.clear()
        self.timestamps.clear()
        print_system("Context cleared")


class Provider(ABC):
    """Implement `_complete()` (and optionally `ensure_loaded()`) to add a backend."""

    def __init__(self, config: Config, budget: TokenBudget | None = None) -> None:
        self.config = config
        self.pconf = config.provider
        self.context = ContextStore(
            max_chars=self.pconf.max_context_tokens * self.pconf.chars_per_token
        )
        self.budget = budget if budget is not None else TokenBudget(self.pconf.daily_token_budget)
        self.lock = asyncio.Lock()
        # Injectable for tests / instant mode.
        self._sleep = asyncio.sleep
        self._rand = random.Random()

    # ~~~ to implement ~~~
    @abstractmethod
    async def _complete(
        self,
        messages: list[dict[str, Any]],
        schema: dict[str, Any] | None,
        model: str,
        raw: bool,
    ) -> CompletionResult:
        """One model call. No retries, no context handling — the base owns those."""

    async def ensure_loaded(self) -> None:  # optional backend hook
        return None

    # ~~~ shared machinery ~~~
    def set_system_prompt(self, prompt: str) -> None:
        self.context.set_system_prompt(prompt)

    @property
    def agent_name(self) -> str:
        return self.context.agent_name

    @agent_name.setter
    def agent_name(self, value: str) -> None:
        self.context.agent_name = value

    async def raw_completion(
        self,
        messages: list[dict[str, Any]],
        schema: dict[str, Any] | None = None,
        model_override: str | None = None,
        max_retries: int = 3,
    ) -> str | None:
        """Background/utility call: no context, no pacing, queues behind the lock."""
        model = model_override or self.pconf.utility_model or self.pconf.model
        async with self.lock:
            for attempt in range(max_retries):
                result = await self._complete(messages, schema, model, raw=True)
                self.budget.record(result.tokens)
                if result.text is not None:
                    return result.text
                print_system(f"raw_completion error: {result.error}")
                if attempt < max_retries - 1:
                    await self._sleep(2)
        return None

    async def generate(
        self,
        user_input: str | None = None,
        schema: dict[str, Any] | None = None,
        skip_delay: bool = False,
        skip_context: bool = False,
        model_override: str | None = None,
        image_urls: list[str] | None = None,
    ) -> dict[str, Any]:
        """Main in-character call: pacing delay, context, full validation loop.

        Returns the validated parsed dict, or {"error": ...} after exhausting
        retries. An out-of-enum value can NEVER be returned.
        """
        if not skip_delay:
            delay = self._rand.randint(
                min(self.pconf.response_delay_min, self.pconf.response_delay_max),
                max(self.pconf.response_delay_min, self.pconf.response_delay_max),
            )
            if delay > 0:
                print_system(f"thinking... ({delay}s)")
                await self._sleep(delay)

        if user_input and not skip_context:
            text = user_input
            if self.pconf.quirks.no_think_suffix:
                text += " /no_think"
            self.context.add("user", text, image_placeholder=bool(image_urls))

        model = model_override or self.pconf.model
        last_error = ""
        for attempt in range(MAX_GENERATE_ATTEMPTS):
            if attempt > 0:
                print_system(f"Retry {attempt}/{MAX_GENERATE_ATTEMPTS - 1}")
            messages = self._build_call_messages(user_input, skip_context, image_urls)

            async with self.lock:
                result = await self._complete(messages, schema, model, raw=False)
            self.budget.record(result.tokens)

            if result.text is None:
                last_error = result.error or "unknown_error"
                # A model that can't process images gets a text-only retry.
                if image_urls and "image" in last_error.lower():
                    print_system("Retrying without image...")
                    image_urls = None
                    continue
                print_system(f"Provider error: {last_error}")
                return {"error": last_error}

            validation = parse_and_validate(result.text, schema)
            if not validation.ok:
                last_error = validation.reason or "invalid"
                print_system(
                    f"Response rejected ({last_error}), attempt "
                    f"{attempt + 1}/{MAX_GENERATE_ATTEMPTS}, regenerating..."
                )
                continue

            parsed = validation.parsed
            assert parsed is not None
            if schema is None:
                if not skip_context:
                    self.context.add("assistant", parsed["response"])
                return parsed

            if not skip_context:
                for key in _CONTEXT_CONTENT_KEYS:
                    if parsed.get(key):
                        self.context.add("assistant", str(parsed[key]))
                        break
            return parsed

        return {"error": f"max_retries_exceeded:{last_error}"}

    def _build_call_messages(
        self,
        user_input: str | None,
        skip_context: bool,
        image_urls: list[str] | None,
    ) -> list[dict[str, Any]]:
        time_str = datetime.now().strftime("%I:%M %p")
        if skip_context:
            messages: list[dict[str, Any]] = []
            if self.context.system_prompt:
                messages.append({"role": "system", "content": self.context.system_prompt})
            if user_input:
                text = f"{user_input}\n[{time_str}]"
                messages.append({"role": "user", "content": text})
        else:
            messages = self.context.build_messages()
            # Current time on the last user turn (API call only, not stored).
            for i in range(len(messages) - 1, -1, -1):
                if messages[i]["role"] == "user" and isinstance(messages[i]["content"], str):
                    messages[i]["content"] += f"\n\nCurrent Time: {time_str}"
                    break
        # Attach real images to the CURRENT user turn only; history keeps the
        # "(image)" placeholder so base64 never bloats the context.
        if image_urls:
            for i in range(len(messages) - 1, -1, -1):
                if messages[i]["role"] == "user":
                    text = messages[i]["content"]
                    parts: list[dict[str, Any]] = [{"type": "text", "text": text}]
                    parts += [{"type": "image_url", "image_url": {"url": u}} for u in image_urls]
                    messages[i] = {**messages[i], "content": parts}
                    break
        return messages


def _safe_print(text: str) -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("ascii", errors="replace").decode("ascii"))


__all__ = [
    "CompletionResult",
    "ContextStore",
    "GenerationError",
    "Provider",
    "Snapshot",
]
