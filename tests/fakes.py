"""A tiny in-memory MemoryStore for tests (no ChromaDB, no embeddings).

Similarity = fraction of the query's words present in the document, which
makes thresholds easy to hit deterministically in tests.
"""

from __future__ import annotations

import uuid
from typing import Any

from elifelse.memory.store import MemoryHit, MemoryStore


def _matches(metadata: dict[str, Any], where: dict[str, Any] | None) -> bool:
    if not where:
        return True
    if "$and" in where:
        return all(_matches(metadata, clause) for clause in where["$and"])
    if "$or" in where:
        return any(_matches(metadata, clause) for clause in where["$or"])
    return all(metadata.get(k) == v for k, v in where.items())


class FakeStore(MemoryStore):
    def __init__(self) -> None:
        self.data: dict[str, list[MemoryHit]] = {}

    async def add(self, collection, text, metadata=None, doc_id=None) -> str:
        doc_id = doc_id or uuid.uuid4().hex
        self.data.setdefault(collection, []).append(
            MemoryHit(id=doc_id, text=text, metadata=dict(metadata or {}))
        )
        return doc_id

    @staticmethod
    def _sim(query: str, doc: str) -> float:
        q = set(query.lower().split())
        d = set(doc.lower().split())
        return len(q & d) / len(q) if q else 0.0

    async def query(self, collection, text, n=5, where=None) -> list[MemoryHit]:
        hits = [
            MemoryHit(id=h.id, text=h.text, similarity=self._sim(text, h.text),
                      metadata=h.metadata)
            for h in self.data.get(collection, [])
            if _matches(h.metadata, where)
        ]
        hits.sort(key=lambda h: h.similarity, reverse=True)
        return hits[:n]

    async def get_all(self, collection, where=None) -> list[MemoryHit]:
        return [h for h in self.data.get(collection, []) if _matches(h.metadata, where)]

    async def delete(self, collection, ids) -> None:
        self.data[collection] = [h for h in self.data.get(collection, []) if h.id not in ids]

    async def count(self, collection) -> int:
        return len(self.data.get(collection, []))
