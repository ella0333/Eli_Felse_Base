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
from elifelse.memory.extraction import FACTS, MEMORIES, extract_batch, summarize_game_batch
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

    # ~~~ game-specific batch processing (3-msg merge) ~~~
    def push_game_message(
        self,
        session_key: str,
        role: str,
        content: str,
        source: str = "",
        activity_type: str = "",
    ) -> None:
        """Game-specific memory push. Every game_batch_size messages get merged
        into a single gameplay memory (no classifier judgment)."""
        game_key = f"game_{session_key}"
        buf = self.buffers.setdefault(game_key, [])
        buf.append(
            {
                "role": role,
                "content": content,
                "source": source or session_key,
                "activity_type": activity_type,
                "timestamp": self.clock().isoformat(),
            }
        )
        if len(buf) >= self.config.game_batch_size:
            batch = buf[: self.config.game_batch_size]
            del buf[: self.config.game_batch_size]
            self._spawn(self._extract_game(batch))

    async def flush_game_remaining(self, session_key: str) -> None:
        """Flush remaining game messages at end of session."""
        game_key = f"game_{session_key}"
        buf = self.buffers.pop(game_key, [])
        if buf:
            await self._extract_game(buf)
        await self.wait_idle()

    async def _extract_game(self, messages: list[dict[str, Any]]) -> None:
        """Summarize a batch of game messages into one gameplay memory."""
        await summarize_game_batch(self.provider, self.store, messages)

    async def consolidate_game_memories(self) -> None:
        """Deduplicate game memories by semantic similarity.
        Keep most recent, remove older near-duplicates."""
        hits = await self.store.get_all(MEMORIES)
        # Filter to game-related activity types
        game_types = {"rpg", "pokemon_blue", "text_rpg"}
        game_hits = [h for h in hits if h.metadata.get("activity_type", "") in game_types]
        if not game_hits:
            print_system("game memory consolidation: no game memories found")
            return

        print_system(f"game memory consolidation: checking {len(game_hits)} memories...")
        to_delete: set[str] = set()

        for hit in game_hits:
            if hit.id in to_delete:
                continue
            similar = await self.store.query(
                MEMORIES, hit.text, n=5,
                where={"activity_type": hit.metadata.get("activity_type", "")},
            )
            for s in similar:
                if s.id == hit.id or s.id in to_delete:
                    continue
                if s.similarity >= self.config.game_dedup_threshold:
                    # Keep the more recent one
                    s_ts = s.metadata.get("timestamp", "")
                    h_ts = hit.metadata.get("timestamp", "")
                    if s_ts > h_ts:
                        to_delete.add(hit.id)
                        break
                    else:
                        to_delete.add(s.id)

        if to_delete:
            await self.store.delete(MEMORIES, list(to_delete))
            print_system(f"game memory consolidation: removed {len(to_delete)} duplicates")
        else:
            print_system("game memory consolidation: no duplicates found")

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
