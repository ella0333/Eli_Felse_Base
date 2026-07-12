"""ChromaDB-backed MemoryStore (the default). Telemetry is off. Cosine space,
so similarity = 1 - distance.

Note: Chroma's default embedding function downloads a small ONNX model on
first use — the first run needs network access once.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from elifelse.memory.store import MemoryHit, MemoryStore


class ChromaStore(MemoryStore):
    def __init__(self, path: Path) -> None:
        import chromadb  # heavy import, kept out of module load
        from chromadb.config import Settings

        self._client = chromadb.PersistentClient(
            path=str(path), settings=Settings(anonymized_telemetry=False)
        )

    def _coll(self, name: str):
        return self._client.get_or_create_collection(name, metadata={"hnsw:space": "cosine"})

    async def add(
        self, collection: str, text: str,
        metadata: dict[str, Any] | None = None, doc_id: str | None = None,
    ) -> str:
        doc_id = doc_id or uuid.uuid4().hex
        self._coll(collection).add(
            ids=[doc_id], documents=[text], metadatas=[metadata] if metadata else None
        )
        return doc_id

    async def query(
        self, collection: str, text: str, n: int = 5,
        where: dict[str, Any] | None = None,
    ) -> list[MemoryHit]:
        coll = self._coll(collection)
        total = coll.count()
        if total == 0:
            return []
        res = coll.query(query_texts=[text], n_results=min(n, total), where=where or None)
        hits = []
        for i, doc_id in enumerate(res["ids"][0]):
            hits.append(
                MemoryHit(
                    id=doc_id,
                    text=res["documents"][0][i],
                    similarity=1.0 - res["distances"][0][i],
                    metadata=(res["metadatas"][0][i] or {}),
                )
            )
        return hits

    async def get_all(
        self, collection: str, where: dict[str, Any] | None = None
    ) -> list[MemoryHit]:
        res = self._coll(collection).get(where=where or None)
        return [
            MemoryHit(id=doc_id, text=res["documents"][i], metadata=(res["metadatas"][i] or {}))
            for i, doc_id in enumerate(res["ids"])
        ]

    async def delete(self, collection: str, ids: list[str]) -> None:
        if ids:
            self._coll(collection).delete(ids=ids)

    async def count(self, collection: str) -> int:
        return self._coll(collection).count()
