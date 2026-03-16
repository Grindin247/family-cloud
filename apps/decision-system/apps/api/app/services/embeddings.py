from __future__ import annotations

import hashlib
from typing import Iterable

from openai import OpenAI

from app.core.config import settings


def _hash_bytes(text: str) -> bytes:
    return hashlib.sha256(text.encode("utf-8")).digest()


def embed_text(text: str, *, dim: int = 1536) -> list[float]:
    """
    Deterministic embedding baseline (no external model required).

    This is NOT semantically strong, but it unblocks pgvector plumbing and API contracts.
    """
    seed = _hash_bytes(text or "")
    out: list[float] = []
    i = 0
    while len(out) < dim:
        b = seed[i % len(seed)]
        out.append((b / 255.0) * 2.0 - 1.0)
        i += 1
    return out


def embed_texts(texts: Iterable[str], *, dim: int = 1536) -> list[list[float]]:
    values = list(texts)
    if not values:
        return []
    if settings.openai_api_key.strip():
        client = OpenAI(api_key=settings.openai_api_key, timeout=settings.note_embedding_timeout_seconds)
        response = client.embeddings.create(
            model=settings.note_embedding_model,
            input=values,
            dimensions=dim,
        )
        return [list(item.embedding) for item in response.data]
    return [embed_text(t, dim=dim) for t in values]
