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

# The collections the framework itself uses. Opened once at startup so a store
# that can't be read fails there, with an explanation, instead of hours later
# in the middle of an activity.
_KNOWN_COLLECTIONS = ("memories", "summaries", "facts")


class StoreUnreadable(Exception):
    """The store exists but this chromadb can't open it."""


class ChromaStore(MemoryStore):
    def __init__(self, path: Path) -> None:
        import chromadb  # heavy import, kept out of module load
        from chromadb.config import Settings

        try:
            self._client = chromadb.PersistentClient(
                path=str(path), settings=Settings(anonymized_telemetry=False)
            )
            for name in _KNOWN_COLLECTIONS:
                self._coll(name)
        except Exception as e:
            # Chroma raises whatever its own loader raises, and none of it says
            # what to do. The common cause by far is a store written by a
            # different chromadb, which surfaces as a KeyError deep in its
            # config parser, so say the useful thing here instead.
            raise StoreUnreadable(
                f"could not open the memory store at {path}\n"
                f"  chromadb {chromadb.__version__} raised {type(e).__name__}: {e}\n"
                f"  Usually this means the store was written by a different "
                f"chromadb, most often because the command being run comes from "
                f"a different environment than the one it was installed into. "
                f"Check 'python -c \"import chromadb, sys; "
                f"print(sys.executable, chromadb.__version__)\"' against the "
                f"environment that created it. Otherwise delete {path} to start "
                f"a fresh store (stored memories are lost; journals, saves and "
                f"profiles are not)."
            ) from e

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
