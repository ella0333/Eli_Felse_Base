"""MemorySystem — the facade the rest of the framework talks to.

- push_message(): buffer a message; a full batch is extracted in the background
- flush_remaining(): end-of-activity flush (the lifecycle calls this)
- recall(): two-tier vector recall (ctx.recall)
- get_facts(): the permanent fact list (used by the base prompt)

Force-flush before trim: every push compares the oldest buffered message with
the oldest message still in the model context — once the context has trimmed
past a buffered message, that buffer is extracted NOW, so nothing the agent
experienced is lost just because the window moved on.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any

from elifelse.config import MemoryConfig
from elifelse.memory.consolidation import consolidate_facts
from elifelse.memory.extraction import FACTS, extract_batch
from elifelse.memory.recall import two_tier_recall
from elifelse.memory.store import MemoryStore
from elifelse.textutils import print_system

if TYPE_CHECKING:
    from elifelse.providers.base import Provider
    from elifelse.structured.registry import SchemaRegistry


class MemorySystem:
    def __init__(
        self,
        provider: Provider,
        store: MemoryStore,
        config: MemoryConfig,
        schemas: SchemaRegistry,
        clock: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.provider = provider
        self.store = store
        self.config = config
        self.schemas = schemas
        self.clock = clock
        # session_key -> buffered messages awaiting extraction
        self.buffers: dict[str, list[dict[str, Any]]] = {}
        self._rules: dict[str, str] = {}
        self._tasks: set[asyncio.Task] = set()

    # ~~~ buffering ~~~
    def push_message(
        self,
        session_key: str,
        role: str,
        content: str,
        source: str = "",
        activity_type: str = "",
        rules: str = "",
    ) -> None:
        buf = self.buffers.setdefault(session_key, [])
        buf.append(
            {
                "role": role,
                "content": content,
                "source": source or session_key,
                "activity_type": activity_type,
                "timestamp": self.clock().isoformat(),
            }
        )
        if rules:
            self._rules[session_key] = rules

        # Context trimmed past our oldest buffered message? Extract it now.
        oldest_ctx = self.provider.context.oldest_timestamp()
        if oldest_ctx and buf[0]["timestamp"] < oldest_ctx and len(buf) < self.config.batch_size:
            print_system(f"context trimmed past buffered messages; flushing '{session_key}'")
            self._spawn(self._extract(session_key, buf[:]))
            buf.clear()
            return

        if len(buf) >= self.config.batch_size:
            batch = buf[: self.config.batch_size]
            del buf[: self.config.batch_size]
            self._spawn(self._extract(session_key, batch))

    async def flush_remaining(self, session_key: str) -> None:
        """Extract whatever is still buffered for a session, then settle."""
        buf = self.buffers.pop(session_key, [])
        if buf:
            await self._extract(session_key, buf)
        await self.wait_idle()

    # ~~~ recall / facts ~~~
    async def recall(self, query: str, source: str) -> list[str]:
        context_horizon = self.provider.context.oldest_timestamp()
        return await two_tier_recall(
            self.store, query, source, self.config,
            context_horizon=context_horizon,
        )

    async def get_facts(self) -> list[str]:
        return [hit.text for hit in await self.store.get_all(FACTS)]

    async def consolidate(self) -> None:
        await consolidate_facts(self.provider, self.store, self.schemas, self.config.max_facts)

    # ~~~ internals ~~~
    async def _extract(self, session_key: str, messages: list[dict[str, Any]]) -> None:
        stored = await extract_batch(
            self.provider, self.store, self.schemas, messages,
            rules=self._rules.get(session_key, ""),
        )
        if stored and await self.store.count(FACTS) > self.config.max_facts:
            await self.consolidate()

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def wait_idle(self) -> None:
        """Wait for all background extraction to finish (tests, shutdown, sleep)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)
