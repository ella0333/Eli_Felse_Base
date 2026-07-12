"""The terminal channel: chat with the agent in the same console it runs in.

Blocking stdin lives in a daemon thread; lines are handed to the asyncio loop
via call_soon_threadsafe, so the single event loop never blocks on input.
Anything you type while the agent is busy queues up as unread messages (they
show up in the menu notification line and can interrupt naps).
"""

from __future__ import annotations

import asyncio
import sys
import threading
from collections import deque
from collections.abc import Callable
from datetime import datetime
from typing import Any

from elifelse.channels.base import Channel


def _safe_print(text: str) -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        enc = sys.stdout.encoding or "ascii"
        print(text.encode(enc, errors="replace").decode(enc))


class TerminalChannel(Channel):
    name = "terminal"

    def __init__(
        self,
        developer_name: str = "Developer",
        agent_name: str = "Agent",
        clock: Callable[[], datetime] = datetime.now,
        command_handler: Callable[[str], bool] | None = None,
    ) -> None:
        self.developer_name = developer_name
        self.agent_name = agent_name
        self.clock = clock
        self.command_handler = command_handler
        self._messages: deque[dict[str, Any]] = deque()
        self._arrived = asyncio.Event()
        self._interrupted = False
        self._thread: threading.Thread | None = None

    # ~~~ stdin reader ~~~
    def start(self) -> None:
        """Begin reading stdin in the background. Call from inside the loop."""
        if self._thread is not None:
            return
        loop = asyncio.get_running_loop()
        self._thread = threading.Thread(
            target=self._read_stdin, args=(loop,), daemon=True, name="terminal-stdin"
        )
        self._thread.start()

    def _read_stdin(self, loop: asyncio.AbstractEventLoop) -> None:
        # Use input() instead of raw sys.stdin iteration so the OS line
        # editor handles arrow keys, backspace, and home/end properly.
        # On Windows this uses the console API; on Unix it uses readline
        # if available.  Raw stdin passes escape codes through, which
        # makes arrow-up scroll into previous terminal output.
        try:
            while True:
                try:
                    text = input().strip()
                except EOFError:
                    break
                if text:
                    loop.call_soon_threadsafe(self.push, text)
        except (ValueError, OSError):
            pass  # stdin closed (shutdown, or captured by a test runner)

    # ~~~ Channel interface ~~~
    def push(self, content: str, sender: str = "") -> None:
        """Queue an incoming message (called by the reader thread, or by tests)."""
        if content.startswith("/") and self.command_handler is not None:
            if self.command_handler(content):
                return  # a control command, not a message for the agent
        self._messages.append(
            {
                "sender": sender or self.developer_name,
                "content": content,
                "timestamp": self.clock().isoformat(),
                "count": 1,
            }
        )
        self._arrived.set()

    async def send(self, text: str) -> bool:
        _safe_print(f"\n{self.agent_name}: {text}")
        try:
            sys.stdout.write("\ntype your reply: ")
            sys.stdout.flush()
        except OSError:
            pass
        return True

    async def wait_for_message(self, timeout: float) -> dict[str, Any] | None:
        if not self._messages:
            self._arrived.clear()
            try:
                await asyncio.wait_for(self._arrived.wait(), timeout)
            except asyncio.TimeoutError:  # noqa: UP041 - distinct class on py3.10
                return None
        if self._interrupted:
            self._interrupted = False
            return None
        if not self._messages:
            return None
        # Merge everything queued (rapid-fire messages become one turn).
        parts = []
        first = self._messages[0]
        count = 0
        while self._messages:
            parts.append(self._messages.popleft()["content"])
            count += 1
        return {**first, "content": "\n".join(parts), "count": count}

    def queue_direct(self, content: str, sender: str = "") -> None:
        """Queue a message bypassing the command handler (for /message)."""
        self._messages.append(
            {
                "sender": sender or self.developer_name,
                "content": content,
                "timestamp": self.clock().isoformat(),
                "count": 1,
            }
        )
        self._arrived.set()

    def unread_count(self) -> int:
        return len(self._messages)

    def interrupt(self) -> None:
        self._interrupted = True
        self._arrived.set()
