from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from agents.common.memory.text import chunk_text
from app.models.memory import MemoryDocument, MemoryEmbedding
from app.services.embeddings import embed_texts


def create_document_with_embeddings(
    db: Session,
    *,
    family_id: int,
    type: str,
    text_value: str,
    source_refs: list[dict[str, Any]] | None = None,
    embed_dim: int = 1536,
) -> MemoryDocument:
    doc = MemoryDocument(
        family_id=family_id,
        type=type,
        text=text_value,
        source_refs_jsonb=source_refs or [],
    )
    db.add(doc)
    db.flush()

    # SQLite test harness: store documents but skip vector embeddings.
    if db.bind is not None and db.bind.dialect.name != "postgresql":
        return doc

    chunks = chunk_text(text_value)
    vectors = embed_texts(chunks, dim=embed_dim)
    for idx, (chunk, vec) in enumerate(zip(chunks, vectors, strict=True)):
        db.add(
            MemoryEmbedding(
                doc_id=doc.doc_id,
                chunk_id=idx,
                embedding=vec,
                metadata_jsonb={"text": chunk, "type": type},
            )
        )
    return doc


def semantic_search(
    db: Session,
    *,
    family_id: int,
    query: str,
    top_k: int = 8,
    embed_dim: int = 1536,
) -> list[dict[str, Any]]:
    if db.bind is not None and db.bind.dialect.name != "postgresql":
        # SQLite fallback: simple substring match against stored docs.
        rows = db.query(MemoryDocument).filter(MemoryDocument.family_id == family_id).all()
        hits = []
        for doc in rows:
            if query.lower() in (doc.text or "").lower():
                hits.append({"doc_id": str(doc.doc_id), "chunk_id": 0, "score": 0.1, "text": doc.text[:500], "metadata": {"type": doc.type}})
        return hits[:top_k]

    qvec = embed_texts([query], dim=embed_dim)[0]
    # pgvector accepts input like '[1,2,3]'::vector
    vec_literal = "[" + ",".join(f"{x:.6f}" for x in qvec) + "]"
    sql = text(
        """
        SELECT e.doc_id::text as doc_id,
               e.chunk_id as chunk_id,
               1.0 / (1.0 + (e.embedding <-> (:qvec)::vector)) as score,
               COALESCE(e.metadata_jsonb->>'text', '') as chunk_text,
               COALESCE(e.metadata_jsonb, '{}'::jsonb) as metadata
        FROM memory_embeddings e
        JOIN memory_documents d ON d.doc_id = e.doc_id
        WHERE d.family_id = :family_id
        ORDER BY e.embedding <-> (:qvec)::vector
        LIMIT :top_k
        """
    )
    rows = db.execute(sql, {"qvec": vec_literal, "family_id": family_id, "top_k": top_k}).mappings().all()
    return [
        {
            "doc_id": row["doc_id"],
            "chunk_id": int(row["chunk_id"]),
            "score": float(row["score"]),
            "text": row["chunk_text"],
            "metadata": dict(row["metadata"] or {}),
        }
        for row in rows
    ]
