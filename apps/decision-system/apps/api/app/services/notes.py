from __future__ import annotations

from datetime import date, datetime, timezone
import re
from typing import Any

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from agents.common.memory.text import chunk_text
from app.models.notes import NoteDocument, NoteEmbedding
from app.schemas.notes import NoteIndexRequest, NoteSearchMatch, NoteSearchRequest
from app.services.embeddings import embed_texts


def _normalize_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _tokenize(value: str) -> list[str]:
    return re.findall(r"[a-z0-9]{2,}", value.lower())


def _lexical_score(doc: NoteDocument, query_tokens: list[str], query_tags: list[str]) -> tuple[float, list[str]]:
    reasons: list[str] = []
    if not query_tokens and not query_tags:
        return 0.0, reasons
    title_tokens = set(_tokenize(doc.title or ""))
    summary_tokens = set(_tokenize(doc.summary or ""))
    body_tokens = set(_tokenize(doc.body_text or ""))
    tags = {str(item).lower() for item in (doc.tags_jsonb or [])}
    score = 0.0
    title_hits = len(title_tokens.intersection(query_tokens))
    summary_hits = len(summary_tokens.intersection(query_tokens))
    body_hits = len(body_tokens.intersection(query_tokens))
    tag_hits = len(tags.intersection({tag.lower() for tag in query_tags}))
    if title_hits:
        score += min(1.0, title_hits / max(1, len(query_tokens))) * 0.45
        reasons.append("Matched title terms")
    if summary_hits:
        score += min(1.0, summary_hits / max(1, len(query_tokens))) * 0.3
        reasons.append("Matched summary terms")
    if body_hits:
        score += min(1.0, body_hits / max(1, len(query_tokens))) * 0.2
    if tag_hits:
        score += min(1.0, tag_hits / max(1, len(query_tags) or 1)) * 0.2
        reasons.append("Matched query tags")
    return min(score, 1.0), reasons


def _recency_score(source_date: date | None, date_from: date | None, date_to: date | None) -> float:
    if source_date is None:
        return 0.0
    if date_from and source_date < date_from:
        return 0.0
    if date_to and source_date > date_to:
        return 0.0
    if date_from or date_to:
        return 1.0
    delta_days = abs((datetime.now(timezone.utc).date() - source_date).days)
    return max(0.0, 1.0 - min(delta_days, 365) / 365.0)


def _item_type_score(item_type: str) -> float:
    if item_type == "polished":
        return 1.0
    if item_type == "raw":
        return 0.7
    return 0.45


def _build_embedding_input(payload: NoteIndexRequest) -> str:
    parts = [
        _normalize_text(payload.title),
        _normalize_text(payload.summary),
        _normalize_text(payload.excerpt_text),
        _normalize_text(payload.body_text),
        " ".join(item.strip() for item in payload.tags if item.strip()),
    ]
    return "\n\n".join(part for part in parts if part).strip()


def upsert_note_document(
    db: Session,
    *,
    payload: NoteIndexRequest,
    embed_dim: int = 1536,
) -> NoteDocument:
    existing = db.execute(select(NoteDocument).where(NoteDocument.path == payload.path)).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if existing is None:
        existing = NoteDocument(
            family_id=payload.family_id,
            actor=payload.actor.strip().lower(),
            source_session_id=(payload.source_session_id or "").strip() or None,
            path=payload.path,
            item_type=payload.item_type,
            role=payload.role,
            title=payload.title,
            summary=payload.summary,
            body_text=payload.body_text,
            excerpt_text=payload.excerpt_text,
            content_type=payload.content_type,
            source_date=payload.source_date,
            tags_jsonb=payload.tags,
            nextcloud_url=payload.nextcloud_url,
            raw_note_url=payload.raw_note_url,
            related_paths_jsonb=payload.related_paths,
            metadata_jsonb=payload.metadata,
            updated_at=now,
        )
        db.add(existing)
        db.flush()
    else:
        existing.family_id = payload.family_id
        existing.actor = payload.actor.strip().lower()
        existing.source_session_id = (payload.source_session_id or "").strip() or None
        existing.item_type = payload.item_type
        existing.role = payload.role
        existing.title = payload.title
        existing.summary = payload.summary
        existing.body_text = payload.body_text
        existing.excerpt_text = payload.excerpt_text
        existing.content_type = payload.content_type
        existing.source_date = payload.source_date
        existing.tags_jsonb = payload.tags
        existing.nextcloud_url = payload.nextcloud_url
        existing.raw_note_url = payload.raw_note_url
        existing.related_paths_jsonb = payload.related_paths
        existing.metadata_jsonb = payload.metadata
        existing.updated_at = now

    db.execute(delete(NoteEmbedding).where(NoteEmbedding.doc_id == existing.doc_id))

    combined_text = _build_embedding_input(payload)
    if combined_text and db.bind is not None and db.bind.dialect.name == "postgresql":
        chunks = chunk_text(combined_text)
        vectors = embed_texts(chunks, dim=embed_dim)
        for idx, (chunk, vec) in enumerate(zip(chunks, vectors, strict=True)):
            db.add(
                NoteEmbedding(
                    doc_id=existing.doc_id,
                    chunk_id=idx,
                    embedding=vec,
                    chunk_text=chunk,
                    metadata_jsonb={"item_type": payload.item_type, "path": payload.path},
                )
            )
    return existing


def _semantic_scores(
    db: Session,
    *,
    family_id: int,
    query: str,
    preferred_item_types: list[str],
    date_from: date | None,
    date_to: date | None,
    top_k: int,
    embed_dim: int,
) -> dict[str, float]:
    if db.bind is None or db.bind.dialect.name != "postgresql":
        return {}
    vector = embed_texts([query], dim=embed_dim)[0]
    vec_literal = "[" + ",".join(f"{value:.6f}" for value in vector) + "]"
    clauses = ["d.family_id = :family_id"]
    params: dict[str, Any] = {"family_id": family_id, "qvec": vec_literal, "limit": max(top_k * 4, 20)}
    if preferred_item_types:
        clauses.append("d.item_type = ANY(:item_types)")
        params["item_types"] = preferred_item_types
    if date_from is not None:
        clauses.append("d.source_date >= :date_from")
        params["date_from"] = date_from
    if date_to is not None:
        clauses.append("d.source_date <= :date_to")
        params["date_to"] = date_to
    sql = text(
        f"""
        SELECT d.path AS path,
               MAX(1.0 / (1.0 + (e.embedding <-> (:qvec)::vector))) AS score
        FROM note_embeddings e
        JOIN note_documents d ON d.doc_id = e.doc_id
        WHERE {' AND '.join(clauses)}
        GROUP BY d.path
        ORDER BY score DESC
        LIMIT :limit
        """
    )
    rows = db.execute(sql, params).mappings().all()
    return {str(row["path"]): float(row["score"]) for row in rows}


def search_notes(
    db: Session,
    *,
    payload: NoteSearchRequest,
    embed_dim: int = 1536,
) -> list[NoteSearchMatch]:
    query = (
        select(NoteDocument)
        .where(NoteDocument.family_id == payload.family_id)
        .order_by(NoteDocument.updated_at.desc())
    )
    if payload.preferred_item_types:
        query = query.where(NoteDocument.item_type.in_(payload.preferred_item_types))
    if payload.date_from is not None:
        query = query.where(NoteDocument.source_date >= payload.date_from)
    if payload.date_to is not None:
        query = query.where(NoteDocument.source_date <= payload.date_to)
    docs = list(db.execute(query).scalars().all())
    if not docs:
        return []

    query_tokens = _tokenize(payload.query)
    semantic_scores = _semantic_scores(
        db,
        family_id=payload.family_id,
        query=payload.query,
        preferred_item_types=payload.preferred_item_types,
        date_from=payload.date_from,
        date_to=payload.date_to,
        top_k=payload.top_k,
        embed_dim=embed_dim,
    )
    ranked: list[tuple[float, NoteDocument, list[str]]] = []
    query_tag_set = [tag.strip().lower() for tag in payload.query_tags if tag.strip()]
    for doc in docs:
        lexical_score, lexical_reasons = _lexical_score(doc, query_tokens, query_tag_set)
        semantic_score = semantic_scores.get(doc.path, 0.0)
        recency = _recency_score(doc.source_date, payload.date_from, payload.date_to)
        item_type_score = _item_type_score(doc.item_type)
        total = (semantic_score * 0.45) + (lexical_score * 0.30) + (recency * 0.15) + (item_type_score * 0.10)
        if total <= 0:
            continue
        reasons = list(dict.fromkeys(lexical_reasons))
        if semantic_score > 0.2:
            reasons.append("Semantic similarity matched the request")
        if payload.date_from or payload.date_to:
            if recency > 0:
                reasons.append("Source date falls inside the requested time window")
        if doc.item_type == "polished":
            reasons.append("Polished note favored for answerability")
        ranked.append((total, doc, reasons))
    ranked.sort(key=lambda item: item[0], reverse=True)
    results: list[NoteSearchMatch] = []
    for score, doc, reasons in ranked[: payload.top_k]:
        excerpt = _normalize_text(doc.excerpt_text or doc.summary or doc.body_text)
        content = doc.body_text if payload.include_content and doc.item_type != "attachment" else None
        if content:
            content = content[:4000]
        results.append(
            NoteSearchMatch(
                path=doc.path,
                item_type=doc.item_type,  # type: ignore[arg-type]
                role=doc.role,  # type: ignore[arg-type]
                title=doc.title,
                summary=doc.summary,
                excerpt=excerpt[:500] or None,
                content=content,
                content_type=doc.content_type,
                source_date=doc.source_date,
                tags=list(doc.tags_jsonb or []),
                nextcloud_url=doc.nextcloud_url,
                raw_note_url=doc.raw_note_url,
                related_paths=list(doc.related_paths_jsonb or []),
                score=round(score, 6),
                match_reasons=reasons,
            )
        )
    return results
