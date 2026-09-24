"""Chroma wrapper: persistent collection, index + query helpers."""

from __future__ import annotations

import hashlib
import uuid

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.config import get_settings
from app.rag.chunker import CodeChunk


def _client() -> chromadb.ClientAPI:
    s = get_settings()
    return chromadb.PersistentClient(
        path=s.chroma_dir, settings=ChromaSettings(anonymized_telemetry=False)
    )


def get_collection():
    s = get_settings()
    client = _client()
    return client.get_or_create_collection(
        name=s.chroma_collection, metadata={"hnsw:space": "cosine"}
    )


def _chunk_id(chunk: CodeChunk) -> str:
    digest = hashlib.sha256(
        f"{chunk.path}:{chunk.name}:{chunk.start_line}:{chunk.content[:500]}".encode()
    ).hexdigest()[:16]
    return f"{chunk.path}::{chunk.name}::{digest}"


class CodeVectorStore:
    """Thin wrapper so nodes.py doesn't touch chromadb directly."""

    def __init__(self):
        self._collection = None

    @property
    def collection(self):
        if self._collection is None:
            self._collection = get_collection()
        return self._collection

    # -- write ------------------------------------------------------ #
    def upsert_chunks(
        self,
        chunks: list[CodeChunk],
        embeddings: list[list[float]],
        repo: str = "local",
    ) -> int:
        if not chunks:
            return 0
        ids = [_chunk_id(c) for c in chunks]
        self.collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=[c.to_document() for c in chunks],
            metadatas=[
                {
                    "path": c.path,
                    "kind": c.kind,
                    "name": c.name,
                    "repo": repo,
                    "start_line": c.start_line,
                    "end_line": c.end_line,
                }
                for c in chunks
            ],
        )
        return len(chunks)

    # -- read ------------------------------------------------------- #
    def query(
        self, query_embedding: list[float], top_k: int = 5, where: dict | None = None
    ) -> list[dict]:
        res = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        docs = res.get("documents", [[]])[0]
        metas = res.get("metadatas", [[]])[0]
        dists = res.get("distances", [[]])[0]
        return [
            {"document": d, "metadata": m, "distance": dist}
            for d, m, dist in zip(docs, metas, dists)
        ]

    def count(self) -> int:
        return self.collection.count()


_store: CodeVectorStore | None = None


def get_store() -> CodeVectorStore:
    global _store
    if _store is None:
        _store = CodeVectorStore()
    return _store


def reset_store_singleton() -> None:
    """Tests only: force re-creation (e.g. after changing CHROMA_DIR)."""
    global _store
    _store = None
    _client().reset() if False else None  # never wipe prod implicitly
    _ = uuid.uuid4()  # keep import used; no-op
