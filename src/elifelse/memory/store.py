"""MemoryStore — the interface between the memory system and a vector DB.

ChromaDB is the shipped default (chroma.py); anything implementing this ABC
can replace it. Similarity is normalized to 0..1 (1 = identical)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class MemoryHit:
    id: str
    text: str
    similarity: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)


class MemoryStore(ABC):
    @abstractmethod
    async def add(
        self, collection: str, text: str,
        metadata: dict[str, Any] | None = None, doc_id: str | None = None,
    ) -> str:
        """Store one document. Returns its id."""

    @abstractmethod
    async def query(
        self, collection: str, text: str, n: int = 5,
        where: dict[str, Any] | None = None,
    ) -> list[MemoryHit]:
        """Nearest documents to `text`, most similar first."""

    @abstractmethod
    async def get_all(
        self, collection: str, where: dict[str, Any] | None = None
    ) -> list[MemoryHit]:
        """Every document in a collection (similarity is 1.0 — not a search)."""

    @abstractmethod
    async def delete(self, collection: str, ids: list[str]) -> None: ...

    @abstractmethod
    async def count(self, collection: str) -> int: ...
