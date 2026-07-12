"""The Channel interface — how people reach the agent.

A channel is a two-way message pipe (terminal, Discord, whatever a module
brings). The framework only ever uses this small surface:

- `send()` delivers the agent's words to the person;
- `wait_for_message()` blocks (with a timeout) for a reply;
- `unread_count()` powers menu notifications and nap interrupts;
- `interrupt()` unblocks a pending wait (graceful stop).

A message is a plain dict: {"sender": str, "content": str, "timestamp": iso,
"count": int} — `count` > 1 means several rapid messages were merged into one.
Message content is model INPUT territory: it is displayed to the model and
stored, never executed.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Channel(ABC):
    name: str = ""

    @abstractmethod
    async def send(self, text: str) -> bool:
        """Deliver the agent's message. Returns False if delivery failed."""

    @abstractmethod
    async def wait_for_message(self, timeout: float) -> dict[str, Any] | None:
        """Wait up to `timeout` seconds for a message. None = timeout/interrupt."""

    @abstractmethod
    def unread_count(self) -> int:
        """Messages waiting that the agent hasn't read yet."""

    @abstractmethod
    def interrupt(self) -> None:
        """Unblock a pending wait_for_message() (it returns None)."""
