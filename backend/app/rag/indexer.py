"""Index a local checkout into Chroma + RAG retrieval helper for the graph."""

from __future__ import annotations

from pathlib import Path

from app.agent.llm import get_embedding_model, is_mock_mode
from app.rag.chunker import CodeChunk, chunk_file, collect_repo_files
from app.rag.vectorstore import get_store


def index_repo(root: str | Path, repo: str = "local", batch: int = 64) -> int:
    """Chunk every indexable file under root and upsert into Chroma.

    Returns number of chunks indexed. In mock mode (no API key) stores
    documents with zero-vectors so the pipeline stays testable? Actually
    Chroma requires real embeddings — in mock mode we skip embedding and
    store via a tiny hash embedding to keep the demo runnable offline.
    """
    root = Path(root)
    files = collect_repo_files(root)
    chunks: list[CodeChunk] = []
    for rel, text in files:
        for c in chunk_file(rel, text):
            # keep chunks modest for embedding models
            if len(c.content) > 8000:
                c.content = c.content[:8000]
            chunks.append(c)

    if not chunks:
        return 0

    if is_mock_mode():
        import hashlib
        import struct

        def fake_embed(text: str) -> list[float]:
            h = hashlib.sha256(text.encode()).digest()
            return [struct.unpack(">f", h[i : i + 4])[0] / 1e38 for i in range(0, 32, 4)]

        store = get_store()
        total = 0
        for i in range(0, len(chunks), batch):
            sub = chunks[i : i + batch]
            store.upsert_chunks(sub, [fake_embed(c.content) for c in sub], repo=repo)
            total += len(sub)
        return total

    model = get_embedding_model()
    store = get_store()
    total = 0
    for i in range(0, len(chunks), batch):
        sub = chunks[i : i + batch]
        vectors = model.embed_documents([c.to_document() for c in sub])
        store.upsert_chunks(sub, vectors, repo=repo)
        total += len(sub)
    return total


def retrieve_related(
    filename: str, patch: str, top_k: int = 5
) -> list[dict]:
    """Retrieve chunks related to a changed file for reviewer context.

    Falls back to path-filtered lookup when embeddings are unavailable.
    """
    from app.config import get_settings

    k = top_k or get_settings().rag_top_k
    query_text = f"{filename}\n{patch[:3000]}"
    try:
        if is_mock_mode():
            # keyword-ish fallback: query with fake embedding, then
            # prefer same-file / same-directory hits
            import hashlib
            import struct

            h = hashlib.sha256(query_text.encode()).digest()
            fake = [struct.unpack(">f", h[i : i + 4])[0] / 1e38 for i in range(0, 32, 4)]
            hits = get_store().query(fake, top_k=k * 3)
        else:
            vec = get_embedding_model().embed_query(query_text)
            hits = get_store().query(vec, top_k=k)
        # boost hits sharing directory / filename tokens
        prefix = filename.rsplit("/", 1)[0] if "/" in filename else ""
        stem = filename.rsplit("/", 1)[-1].split(".")[0].lower()

        def score(h: dict) -> tuple[int, float]:
            meta = h.get("metadata", {}) or {}
            p = str(meta.get("path", ""))
            bonus = 0
            if prefix and p.startswith(prefix):
                bonus -= 1
            if stem and stem in p.lower():
                bonus -= 1
            return (bonus, float(h.get("distance", 9)))

        return sorted(hits, key=score)[:k]
    except Exception:
        return []


def format_rag_context(hits: list[dict], max_chars: int = 4000) -> str:
    if not hits:
        return "(관련 코드 검색 결과 없음)"
    parts: list[str] = []
    used = 0
    for h in hits:
        doc = str(h.get("document", ""))[:1500]
        if used + len(doc) > max_chars:
            break
        parts.append(doc)
        used += len(doc)
    return "\n\n---\n\n".join(parts)
