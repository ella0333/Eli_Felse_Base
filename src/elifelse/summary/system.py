"""Activity summaries.

After every activity the lifecycle hands the new messages here; the utility
model produces one short summary, stored in the vector store with metadata
(activity_type, subject, timestamp, date, time). Isolated activities get the
summary injected as their one compact context line.

Activities may declare their own transcript formatter (format_transcript);
a huge transcript is chunked by paragraphs, summarized per chunk, then the
chunk summaries are combined and summarized once more.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any

from elifelse.config import SummaryConfig
from elifelse.memory.store import MemoryStore
from elifelse.structured.validation import parse_and_validate
from elifelse.textutils import print_system

if TYPE_CHECKING:
    from elifelse.providers.base import Provider

SUMMARIES = "summaries"

SUMMARY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"summary": {"type": "string"}},
    "required": ["summary"],
    "additionalProperties": False,
}

_SYSTEM = (
    "You write compact activity summaries. Summarize the transcript in a few "
    "sentences: what happened, anything notable, how it ended. Third person, "
    "past tense, no preamble."
)


class SummarySystem:
    def __init__(
        self,
        provider: Provider,
        store: MemoryStore,
        config: SummaryConfig,
        agent_name: str,
        developer_name: str = "Owner",
        clock: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.provider = provider
        self.store = store
        self.config = config
        self.agent_name = agent_name
        self.developer_name = developer_name
        self.clock = clock

    # ~~~ formatting ~~~
    def default_format(self, messages: list[dict[str, Any]]) -> str:
        lines = []
        for msg in messages:
            content = msg.get("content", "")
            if not isinstance(content, str):
                continue
            who = self.agent_name if msg.get("role") == "assistant" else self.developer_name
            lines.append(f"{who}: {content}")
        return "\n".join(lines)

    @staticmethod
    def chunk(text: str, max_chars: int) -> list[str]:
        """Split on paragraph boundaries into pieces of at most max_chars."""
        if len(text) <= max_chars:
            return [text]
        chunks: list[str] = []
        current = ""
        for para in text.split("\n"):
            candidate = f"{current}\n{para}" if current else para
            if len(candidate) > max_chars and current:
                chunks.append(current)
                current = para
            else:
                current = candidate
            # A single paragraph longer than the cap gets hard-split.
            while len(current) > max_chars:
                chunks.append(current[:max_chars])
                current = current[max_chars:]
        if current:
            chunks.append(current)
        return chunks

    # ~~~ generate + store ~~~
    async def generate_and_store(
        self,
        activity_type: str,
        subject: str,
        messages: list[dict[str, Any]],
        formatter: Callable[[list[dict[str, Any]]], str | None] | None = None,
    ) -> str | None:
        transcript = formatter(messages) if formatter else None
        if transcript is None:
            transcript = self.default_format(messages)
        if not transcript.strip():
            return None

        parts = [
            await self._summarize(chunk)
            for chunk in self.chunk(transcript, self.config.chunk_chars)
        ]
        parts = [p for p in parts if p]
        if not parts:
            print_system(f"summary failed for '{activity_type}'; skipping")
            return None
        summary = parts[0] if len(parts) == 1 else await self._summarize("\n\n".join(parts))
        if not summary:
            return None

        now = self.clock()
        await self.store.add(
            SUMMARIES,
            summary,
            {
                "activity_type": activity_type,
                "subject": subject,
                "timestamp": now.isoformat(),
                "date": now.strftime("%Y-%m-%d"),
                "time": now.strftime("%I:%M %p"),
            },
        )
        return summary

    async def latest(
        self, activity_type: str | None = None, subject: str | None = None
    ) -> str | None:
        """The most recent stored summary, optionally filtered."""
        clauses = []
        if activity_type is not None:
            clauses.append({"activity_type": activity_type})
        if subject is not None:
            clauses.append({"subject": subject})
        where: dict[str, Any] | None = None
        if len(clauses) == 1:
            where = clauses[0]
        elif clauses:
            where = {"$and": clauses}
        hits = await self.store.get_all(SUMMARIES, where=where)
        if not hits:
            return None
        hits.sort(key=lambda h: h.metadata.get("timestamp", ""), reverse=True)
        return hits[0].text

    async def _summarize(self, text: str) -> str | None:
        raw = await self.provider.raw_completion(
            [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": text},
            ],
            schema=SUMMARY_SCHEMA,
        )
        if raw is None:
            return None
        validation = parse_and_validate(raw, SUMMARY_SCHEMA)
        if not validation.ok or validation.parsed is None:
            return None
        summary = str(validation.parsed.get("summary", "")).strip()
        return summary or None
