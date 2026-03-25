from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
import hashlib
import json
import logging
import posixpath
import re
from typing import Any, Literal

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.documents import Document, DocumentChunk
from app.schemas.files import FileIndexRequest, FileSearchMatch, FileSearchRequest, SourceRef
from app.schemas.notes import NoteIndexRequest, NoteSearchMatch, NoteSearchRequest
from app.schemas.search import UnifiedSearchMatch, UnifiedSearchRequest
from app.services.embeddings import embed_texts

LOGGER = logging.getLogger(__name__)
TOKEN_RE = re.compile(r"[a-z0-9]{2,}")


@dataclass(frozen=True)
class RankedDocument:
    doc: Document
    score: float
    reasons: list[str]
    source_refs: list[dict[str, Any]]


def _normalize_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _tokenize(value: str) -> list[str]:
    return TOKEN_RE.findall((value or "").lower())


def _para_bucket_from_path(path: str) -> str | None:
    normalized = path.strip()
    for bucket in ("Projects", "Areas", "Resources", "Archive", "Inbox", "Unfiled"):
        if f"/{bucket}/" in normalized or normalized.endswith(f"/{bucket}"):
            return bucket
    return None


def _chunk_text(text: str) -> list[str]:
    raw = (text or "").strip()
    if not raw:
        return []
    max_chars = max(200, settings.file_chunk_size_chars)
    overlap = max(0, min(settings.file_chunk_overlap_chars, max_chars // 2))
    chunks: list[str] = []
    start = 0
    while start < len(raw):
        end = min(len(raw), start + max_chars)
        chunk = raw[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(raw):
            break
        start = max(0, end - overlap)
    return chunks


def _default_source_refs(path: str, title: str | None, existing: list[SourceRef] | list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if existing:
        normalized: list[dict[str, Any]] = []
        for item in existing:
            if isinstance(item, SourceRef):
                normalized.append(item.model_dump(exclude_none=True))
            elif isinstance(item, dict):
                normalized.append({key: value for key, value in item.items() if value is not None})
        if normalized:
            return normalized
    return [{"label": title or posixpath.basename(path), "path": path, "locator_type": "path", "locator_value": path}]


def _content_hash(*, body_text: str | None, content_hash: str | None, etag: str | None, path: str, size_bytes: int | None) -> str | None:
    if content_hash:
        return content_hash.strip() or None
    if body_text:
        return hashlib.sha256(body_text.encode("utf-8")).hexdigest()
    if etag:
        return hashlib.sha256(f"{etag}:{size_bytes or 0}:{path}".encode("utf-8")).hexdigest()
    return None


def _build_embedding_input(
    *,
    name: str | None,
    title: str | None,
    summary: str | None,
    excerpt_text: str | None,
    body_text: str | None,
    tags: list[str],
) -> str:
    parts = [
        _normalize_text(name),
        _normalize_text(title),
        _normalize_text(summary),
        _normalize_text(excerpt_text),
        _normalize_text(body_text),
        " ".join(item.strip() for item in tags if item.strip()),
    ]
    return "\n\n".join(part for part in parts if part).strip()


def _resolve_existing_document(db: Session, *, family_id: int, provider: str, provider_file_id: str | None, path: str) -> Document | None:
    existing = None
    if provider_file_id:
        existing = db.execute(
            select(Document).where(
                Document.family_id == family_id,
                Document.provider == provider,
                Document.provider_file_id == provider_file_id,
            )
        ).scalar_one_or_none()
    if existing is None:
        existing = db.execute(
            select(Document).where(Document.family_id == family_id, Document.path == path)
        ).scalar_one_or_none()
    return existing


def _supports_vector_search(db: Session) -> bool:
    return bool(db.bind is not None and db.bind.dialect.name == "postgresql")


def _chunk_metadata(*, path: str, document_kind: str, item_type: str) -> dict[str, Any]:
    return {"path": path, "document_kind": document_kind, "item_type": item_type}


def _load_document_chunks(db: Session, *, doc_id: Any) -> list[DocumentChunk]:
    return list(
        db.execute(
            select(DocumentChunk).where(DocumentChunk.doc_id == doc_id).order_by(DocumentChunk.chunk_id.asc())
        ).scalars().all()
    )


def _queue_reindex_job(
    db: Session,
    *,
    family_id: int,
    actor: str,
    path: str,
    provider_file_id: str | None,
    document_kind: str,
) -> None:
    from app.services.jobs import enqueue_job

    enqueue_job(
        db,
        family_id=family_id,
        job_type="reindex_document",
        actor=actor,
        dedupe_key=f"reindex:{path}",
        payload={"path": path, "provider_file_id": provider_file_id, "document_kind": document_kind},
    )


def _sync_document_chunks(
    db: Session,
    *,
    document: Document,
    actor: str,
    combined_text: str,
    source_refs: list[dict[str, Any]],
    queue_retry_on_failure: bool,
    force_reembed: bool = False,
) -> dict[str, Any]:
    existing_chunks = _load_document_chunks(db, doc_id=document.doc_id)
    first_ref = source_refs[0] if source_refs else None
    metadata = _chunk_metadata(path=document.path, document_kind=document.document_kind, item_type=document.item_type)
    duplicate_of = None
    if isinstance(document.metadata_jsonb, dict):
        duplicate_of = document.metadata_jsonb.get("duplicate_of")
    if not combined_text or duplicate_of:
        if existing_chunks:
            db.execute(delete(DocumentChunk).where(DocumentChunk.doc_id == document.doc_id))
        return {"chunk_count": 0, "reused": False}

    chunks = _chunk_text(combined_text)
    existing_texts = [chunk.chunk_text for chunk in existing_chunks]
    missing_semantic_vectors = _supports_vector_search(db) and all(chunk.embedding is None for chunk in existing_chunks)
    if existing_chunks and existing_texts == chunks and not (force_reembed and missing_semantic_vectors):
        for chunk in existing_chunks:
            chunk.source_ref_jsonb = first_ref
            chunk.metadata_jsonb = metadata
        if missing_semantic_vectors:
            document.ingestion_status = "indexed_lexical_only"
        return {"chunk_count": len(chunks), "reused": True}

    if existing_chunks:
        db.execute(delete(DocumentChunk).where(DocumentChunk.doc_id == document.doc_id))

    vectors: list[list[float] | None] = [None] * len(chunks)
    if _supports_vector_search(db):
        try:
            embedded = embed_texts(chunks, is_query=False, dim=settings.file_embedding_dim)
            for index, vector in enumerate(embedded[: len(chunks)]):
                vectors[index] = vector
        except Exception as exc:
            LOGGER.warning("document_embedding_failed doc=%s error=%s", document.path, exc)
            document.ingestion_status = "indexed_lexical_only"
            if queue_retry_on_failure:
                _queue_reindex_job(
                    db,
                    family_id=document.family_id,
                    actor=actor,
                    path=document.path,
                    provider_file_id=document.provider_file_id,
                    document_kind=document.document_kind,
                )

    for index, chunk in enumerate(chunks):
        db.add(
            DocumentChunk(
                doc_id=document.doc_id,
                chunk_id=index,
                chunk_kind="body",
                chunk_text=chunk,
                embedding=vectors[index] if index < len(vectors) else None,
                source_ref_jsonb=first_ref,
                metadata_jsonb=metadata,
            )
        )
    return {"chunk_count": len(chunks), "reused": False}


def _combined_text_for_document(doc: Document) -> str:
    return _build_embedding_input(
        name=doc.name,
        title=doc.title,
        summary=doc.summary,
        excerpt_text=doc.excerpt_text,
        body_text=doc.body_text,
        tags=list(doc.tags_jsonb or []),
    )


def _upsert_document_from_payload(
    db: Session,
    *,
    family_id: int,
    document_kind: Literal["file", "note"],
    actor: str,
    owner_person_id: str | None,
    visibility_scope: str,
    source_session_id: str | None,
    source_agent_id: str,
    source_runtime: str,
    path: str,
    name: str | None,
    item_type: str,
    role: str,
    title: str | None,
    summary: str | None,
    body_text: str | None,
    excerpt_text: str | None,
    content_type: str | None,
    media_kind: str | None,
    source_date: date | None,
    modified_at: datetime | None,
    size_bytes: int | None,
    etag: str | None,
    content_hash: str | None,
    provider_file_id: str | None,
    is_directory: bool,
    tags: list[str],
    nextcloud_url: str | None,
    raw_note_url: str | None,
    related_paths: list[str],
    source_refs: list[SourceRef] | list[dict[str, Any]],
    metadata: dict[str, Any],
) -> Document:
    existing = _resolve_existing_document(db, family_id=family_id, provider="nextcloud", provider_file_id=provider_file_id, path=path)
    now = datetime.now(UTC)
    normalized_source_refs = _default_source_refs(path, title, source_refs)
    body = (body_text or "")[: settings.file_max_body_chars] or None
    summary_text = (summary or "")[: settings.file_max_body_chars] or None
    excerpt = (excerpt_text or summary_text or body or "")[: settings.file_max_excerpt_chars] or None
    doc_metadata = dict(metadata or {})
    content_hash_value = _content_hash(body_text=body, content_hash=content_hash, etag=etag, path=path, size_bytes=size_bytes)
    duplicate_of = None
    if content_hash_value:
        duplicate = db.execute(
            select(Document).where(
                Document.family_id == family_id,
                Document.content_hash == content_hash_value,
                Document.doc_id != (existing.doc_id if existing is not None else None),
            )
        ).scalar_one_or_none()
        if duplicate is not None:
            duplicate_of = str(duplicate.doc_id)
            doc_metadata["duplicate_of"] = duplicate_of
    para_bucket = _para_bucket_from_path(path) or str(doc_metadata.get("destination_folder") or "")
    extraction_profile = str(doc_metadata.get("extraction_profile") or ("metadata" if not body else "text"))
    ingestion_status = str(doc_metadata.get("ingestion_status") or ("deferred_duplicate" if duplicate_of else ("indexed" if body or summary_text else "indexed_metadata")))

    if existing is None:
        existing = Document(
            family_id=family_id,
            owner_person_id=owner_person_id,
            actor=actor,
            source_agent_id=source_agent_id,
            source_runtime=source_runtime,
            visibility_scope=visibility_scope,
            source_session_id=(source_session_id or "").strip() or None,
            provider="nextcloud",
            provider_file_id=provider_file_id,
            path=path,
            name=name,
            document_kind=document_kind,
            item_type=item_type,
            role=role,
            title=title,
            summary=summary_text,
            body_text=body,
            excerpt_text=excerpt,
            content_type=content_type,
            media_kind=media_kind,
            source_date=source_date,
            size_bytes=size_bytes,
            modified_at=modified_at,
            etag=etag,
            content_hash=content_hash_value,
            is_directory=is_directory,
            para_bucket=para_bucket or None,
            extraction_profile=extraction_profile,
            ingestion_status=ingestion_status,
            tags_jsonb=tags,
            nextcloud_url=nextcloud_url,
            raw_note_url=raw_note_url,
            related_paths_jsonb=related_paths,
            source_refs_jsonb=normalized_source_refs,
            metadata_jsonb=doc_metadata,
            updated_at=now,
        )
        db.add(existing)
        db.flush()
    else:
        existing.family_id = family_id
        existing.owner_person_id = owner_person_id
        existing.actor = actor
        existing.source_agent_id = source_agent_id
        existing.source_runtime = source_runtime
        existing.visibility_scope = visibility_scope
        existing.source_session_id = (source_session_id or "").strip() or None
        existing.provider = "nextcloud"
        existing.provider_file_id = provider_file_id
        existing.path = path
        existing.name = name
        existing.document_kind = document_kind
        existing.item_type = item_type
        existing.role = role
        existing.title = title
        existing.summary = summary_text
        existing.body_text = body
        existing.excerpt_text = excerpt
        existing.content_type = content_type
        existing.media_kind = media_kind
        existing.source_date = source_date
        existing.size_bytes = size_bytes
        existing.modified_at = modified_at
        existing.etag = etag
        existing.content_hash = content_hash_value
        existing.is_directory = is_directory
        existing.para_bucket = para_bucket or None
        existing.extraction_profile = extraction_profile
        existing.ingestion_status = ingestion_status
        existing.tags_jsonb = tags
        existing.nextcloud_url = nextcloud_url
        existing.raw_note_url = raw_note_url
        existing.related_paths_jsonb = related_paths
        existing.source_refs_jsonb = normalized_source_refs
        existing.metadata_jsonb = doc_metadata
        existing.updated_at = now

    combined_text = _build_embedding_input(
        name=name,
        title=title,
        summary=summary_text,
        excerpt_text=excerpt,
        body_text=body,
        tags=tags,
    )
    _sync_document_chunks(
        db,
        document=existing,
        actor=actor,
        combined_text=combined_text,
        source_refs=normalized_source_refs,
        queue_retry_on_failure=True,
        force_reembed=False,
    )

    if settings.file_memory_mirror_enabled and summary_text and source_agent_id == "FileAgent" and document_kind in {"file", "note"}:
        from app.services.jobs import enqueue_job

        text = "\n".join(part for part in [title or "", summary_text, path] if part).strip()
        enqueue_job(
            db,
            family_id=family_id,
            job_type="mirror_memory",
            actor=actor,
            dedupe_key=f"memory:{path}",
            payload={
                "actor": actor,
                "type": "note",
                "text": text,
                "owner_person_id": owner_person_id,
                "visibility_scope": visibility_scope,
                "source_refs": normalized_source_refs,
            },
        )
    return existing


def reindex_document(db: Session, *, document: Document) -> dict[str, Any]:
    combined_text = _combined_text_for_document(document)
    result = _sync_document_chunks(
        db,
        document=document,
        actor=document.actor,
        combined_text=combined_text,
        source_refs=list(document.source_refs_jsonb or []),
        queue_retry_on_failure=False,
        force_reembed=True,
    )
    document.updated_at = datetime.now(UTC)
    return {
        "doc_id": str(document.doc_id),
        "path": document.path,
        "ingestion_status": document.ingestion_status,
        **result,
    }


def upsert_file_document(db: Session, *, payload: FileIndexRequest) -> Document:
    return _upsert_document_from_payload(
        db,
        family_id=payload.family_id,
        document_kind="file",
        actor=payload.actor.strip().lower(),
        owner_person_id=payload.owner_person_id,
        visibility_scope=payload.visibility_scope,
        source_session_id=payload.source_session_id,
        source_agent_id=payload.source_agent_id,
        source_runtime=payload.source_runtime,
        path=payload.path,
        name=payload.name,
        item_type=payload.item_type,
        role=payload.role,
        title=payload.title,
        summary=payload.summary,
        body_text=payload.body_text,
        excerpt_text=payload.excerpt_text,
        content_type=payload.content_type,
        media_kind=payload.media_kind,
        source_date=payload.source_date,
        modified_at=payload.modified_at,
        size_bytes=payload.size_bytes,
        etag=payload.etag,
        content_hash=payload.content_hash,
        provider_file_id=payload.file_id,
        is_directory=payload.is_directory,
        tags=list(payload.tags),
        nextcloud_url=payload.nextcloud_url,
        raw_note_url=None,
        related_paths=list(payload.related_paths),
        source_refs=list(payload.source_refs),
        metadata=dict(payload.metadata),
    )


def upsert_note_document(db: Session, *, payload: NoteIndexRequest) -> Document:
    return _upsert_document_from_payload(
        db,
        family_id=payload.family_id,
        document_kind="note",
        actor=payload.actor.strip().lower(),
        owner_person_id=payload.owner_person_id,
        visibility_scope=payload.visibility_scope,
        source_session_id=payload.source_session_id,
        source_agent_id=payload.source_agent_id,
        source_runtime=payload.source_runtime,
        path=payload.path,
        name=payload.name,
        item_type=payload.item_type,
        role=payload.role,
        title=payload.title,
        summary=payload.summary,
        body_text=payload.body_text,
        excerpt_text=payload.excerpt_text,
        content_type=payload.content_type,
        media_kind="text",
        source_date=payload.source_date,
        modified_at=payload.modified_at,
        size_bytes=payload.size_bytes,
        etag=payload.etag,
        content_hash=payload.content_hash,
        provider_file_id=payload.file_id,
        is_directory=False,
        tags=list(payload.tags),
        nextcloud_url=payload.nextcloud_url,
        raw_note_url=payload.raw_note_url,
        related_paths=list(payload.related_paths),
        source_refs=list(payload.source_refs),
        metadata=dict(payload.metadata),
    )


def _lexical_score(doc: Document, *, query_tokens: list[str], query_tags: list[str]) -> tuple[float, list[str]]:
    reasons: list[str] = []
    if not query_tokens and not query_tags:
        return 0.0, reasons
    path_tokens = set(_tokenize(doc.path))
    name_tokens = set(_tokenize(doc.name or ""))
    title_tokens = set(_tokenize(doc.title or ""))
    summary_tokens = set(_tokenize(doc.summary or ""))
    body_tokens = set(_tokenize(doc.body_text or ""))
    tags = {str(item).lower() for item in (doc.tags_jsonb or [])}
    score = 0.0
    if title_tokens.intersection(query_tokens):
        score += 0.35
        reasons.append("Matched title terms")
    if name_tokens.intersection(query_tokens):
        score += 0.15
        reasons.append("Matched filename terms")
    if path_tokens.intersection(query_tokens):
        score += 0.15
        reasons.append("Matched folder/path terms")
    if summary_tokens.intersection(query_tokens):
        score += 0.2
        reasons.append("Matched summary terms")
    if body_tokens.intersection(query_tokens):
        score += 0.2
        reasons.append("Matched body terms")
    if tags.intersection(query_tags):
        score += 0.15
        reasons.append("Matched query tags")
    return min(score, 1.0), list(dict.fromkeys(reasons))


def _recency_bonus(doc: Document, *, date_from: date | None, date_to: date | None) -> float:
    if doc.source_date is None:
        return 0.0
    if date_from and doc.source_date < date_from:
        return 0.0
    if date_to and doc.source_date > date_to:
        return 0.0
    if date_from or date_to:
        return 0.1
    delta_days = abs((datetime.now(UTC).date() - doc.source_date).days)
    return max(0.0, 0.1 - min(delta_days, 365) / 3650.0)


def _semantic_scores(
    db: Session,
    *,
    family_id: int,
    query: str,
    owner_person_id: str | None,
    document_kinds: list[str],
    preferred_item_types: list[str],
    content_types: list[str],
    date_from: date | None,
    date_to: date | None,
    top_k: int,
) -> dict[str, tuple[float, dict[str, Any] | None]]:
    if not _supports_vector_search(db):
        return {}
    try:
        vector = embed_texts([query], is_query=True, dim=settings.file_embedding_dim)[0]
    except Exception as exc:
        LOGGER.warning("semantic_query_embedding_failed query=%s error=%s", query, exc)
        return {}
    vec_literal = "[" + ",".join(f"{value:.6f}" for value in vector) + "]"
    clauses = ["d.family_id = :family_id", "c.embedding IS NOT NULL"]
    params: dict[str, Any] = {"family_id": family_id, "qvec": vec_literal, "limit": max(top_k * 4, 20)}
    if owner_person_id is not None:
        clauses.append("d.owner_person_id = :owner_person_id")
        params["owner_person_id"] = owner_person_id
    if document_kinds:
        clauses.append("d.document_kind = ANY(:document_kinds)")
        params["document_kinds"] = document_kinds
    if preferred_item_types:
        clauses.append("d.item_type = ANY(:item_types)")
        params["item_types"] = preferred_item_types
    if content_types:
        clauses.append("d.content_type = ANY(:content_types)")
        params["content_types"] = content_types
    if date_from is not None:
        clauses.append("d.source_date >= :date_from")
        params["date_from"] = date_from
    if date_to is not None:
        clauses.append("d.source_date <= :date_to")
        params["date_to"] = date_to
    sql = text(
        f"""
        SELECT ranked.doc_id,
               ranked.score,
               ranked.source_ref_jsonb
        FROM (
            SELECT d.doc_id::text AS doc_id,
                   c.source_ref_jsonb AS source_ref_jsonb,
                   1.0 / (1.0 + (c.embedding <-> (:qvec)::vector)) AS score,
                   ROW_NUMBER() OVER (PARTITION BY d.doc_id ORDER BY c.embedding <-> (:qvec)::vector ASC) AS chunk_rank
            FROM document_chunks c
            JOIN documents d ON d.doc_id = c.doc_id
            WHERE {' AND '.join(clauses)}
        ) ranked
        WHERE ranked.chunk_rank = 1
        ORDER BY ranked.score DESC
        LIMIT :limit
        """
    )
    rows = db.execute(sql, params).mappings().all()
    return {
        str(row["doc_id"]): (
            float(row["score"]),
            row["source_ref_jsonb"] if isinstance(row["source_ref_jsonb"], dict) else None,
        )
        for row in rows
    }


def _query_documents(
    db: Session,
    *,
    family_id: int,
    owner_person_id: str | None,
    document_kinds: list[str],
    preferred_item_types: list[str],
    content_types: list[str],
    date_from: date | None,
    date_to: date | None,
) -> list[Document]:
    query = select(Document).where(Document.family_id == family_id).order_by(Document.updated_at.desc())
    if owner_person_id is not None:
        query = query.where(Document.owner_person_id == owner_person_id)
    if document_kinds:
        query = query.where(Document.document_kind.in_(document_kinds))
    if preferred_item_types:
        query = query.where(Document.item_type.in_(preferred_item_types))
    if content_types:
        query = query.where(Document.content_type.in_(content_types))
    if date_from is not None:
        query = query.where(Document.source_date >= date_from)
    if date_to is not None:
        query = query.where(Document.source_date <= date_to)
    return list(db.execute(query).scalars().all())


def search_documents(
    db: Session,
    *,
    family_id: int,
    owner_person_id: str | None,
    query_text: str,
    top_k: int,
    document_kinds: list[str],
    preferred_item_types: list[str],
    content_types: list[str],
    query_tags: list[str],
    date_from: date | None,
    date_to: date | None,
) -> list[RankedDocument]:
    docs = _query_documents(
        db,
        family_id=family_id,
        owner_person_id=owner_person_id,
        document_kinds=document_kinds,
        preferred_item_types=preferred_item_types,
        content_types=content_types,
        date_from=date_from,
        date_to=date_to,
    )
    if not docs:
        return []
    tokens = _tokenize(query_text)
    tag_tokens = [tag.strip().lower() for tag in query_tags if tag.strip()]
    lexical_ranked: list[tuple[float, Document, list[str]]] = []
    for doc in docs:
        score, reasons = _lexical_score(doc, query_tokens=tokens, query_tags=tag_tokens)
        if score > 0:
            lexical_ranked.append((score, doc, reasons))
    lexical_ranked.sort(key=lambda item: item[0], reverse=True)
    semantic_rank_map = _semantic_scores(
        db,
        family_id=family_id,
        query=query_text,
        owner_person_id=owner_person_id,
        document_kinds=document_kinds,
        preferred_item_types=preferred_item_types,
        content_types=content_types,
        date_from=date_from,
        date_to=date_to,
        top_k=top_k,
    )
    lexical_rank_map = {str(item[1].doc_id): idx + 1 for idx, item in enumerate(lexical_ranked)}
    lexical_reason_map = {str(item[1].doc_id): item[2] for item in lexical_ranked}
    semantic_sorted = sorted(semantic_rank_map.items(), key=lambda item: item[1][0], reverse=True)
    semantic_rank_only = {doc_id: idx + 1 for idx, (doc_id, _) in enumerate(semantic_sorted)}

    ranked: list[RankedDocument] = []
    for doc in docs:
        doc_id = str(doc.doc_id)
        reasons = list(dict.fromkeys(lexical_reason_map.get(doc_id, [])))
        score = 0.0
        if doc_id in lexical_rank_map:
            score += 1.0 / (60 + lexical_rank_map[doc_id])
        if doc_id in semantic_rank_only:
            score += 1.0 / (60 + semantic_rank_only[doc_id])
            reasons.append("Semantic similarity matched the request")
        score += _recency_bonus(doc, date_from=date_from, date_to=date_to)
        if doc.document_kind == "note" and doc.item_type == "polished":
            score += 0.01
            reasons.append("Polished note favored for answerability")
        if not reasons and query_text.strip():
            continue
        source_refs = list(doc.source_refs_jsonb or [])
        semantic_source = semantic_rank_map.get(doc_id, (0.0, None))[1]
        if semantic_source is not None:
            source_refs = [semantic_source] + [item for item in source_refs if item != semantic_source]
        ranked.append(RankedDocument(doc=doc, score=round(score, 6), reasons=list(dict.fromkeys(reasons)), source_refs=source_refs[:3]))
    ranked.sort(key=lambda item: item.score, reverse=True)
    return ranked[:top_k]


def _excerpt_for_doc(doc: Document) -> str | None:
    return _normalize_text(doc.excerpt_text or doc.summary or doc.body_text)[: settings.file_max_excerpt_chars] or None


def _content_for_doc(doc: Document, *, include_content: bool) -> str | None:
    if not include_content or doc.is_directory:
        return None
    if doc.document_kind == "note" and doc.item_type == "attachment":
        return None
    return (doc.body_text or "")[: settings.file_max_inline_content_chars] or None


def _refs(items: list[dict[str, Any]]) -> list[SourceRef]:
    return [SourceRef.model_validate(item) for item in items if isinstance(item, dict)]


def search_files(db: Session, *, payload: FileSearchRequest) -> list[FileSearchMatch]:
    ranked = search_documents(
        db,
        family_id=payload.family_id,
        owner_person_id=payload.owner_person_id,
        query_text=payload.query,
        top_k=payload.top_k,
        document_kinds=["file"],
        preferred_item_types=list(payload.preferred_item_types),
        content_types=list(payload.content_types),
        query_tags=list(payload.query_tags),
        date_from=payload.date_from,
        date_to=payload.date_to,
    )
    return [
        FileSearchMatch(
            path=item.doc.path,
            owner_person_id=item.doc.owner_person_id,
            visibility_scope=item.doc.visibility_scope,
            name=item.doc.name,
            item_type=item.doc.item_type,  # type: ignore[arg-type]
            role=item.doc.role,  # type: ignore[arg-type]
            title=item.doc.title,
            summary=item.doc.summary,
            excerpt=_excerpt_for_doc(item.doc),
            content=_content_for_doc(item.doc, include_content=payload.include_content),
            content_type=item.doc.content_type,
            media_kind=item.doc.media_kind,
            source_date=item.doc.source_date,
            size_bytes=item.doc.size_bytes,
            etag=item.doc.etag,
            file_id=item.doc.provider_file_id,
            tags=list(item.doc.tags_jsonb or []),
            nextcloud_url=item.doc.nextcloud_url,
            related_paths=list(item.doc.related_paths_jsonb or []),
            source_refs=_refs(item.source_refs),
            score=item.score,
            match_reasons=item.reasons,
        )
        for item in ranked
    ]


def search_notes(db: Session, *, payload: NoteSearchRequest) -> list[NoteSearchMatch]:
    ranked = search_documents(
        db,
        family_id=payload.family_id,
        owner_person_id=payload.owner_person_id,
        query_text=payload.query,
        top_k=payload.top_k,
        document_kinds=["note"],
        preferred_item_types=list(payload.preferred_item_types),
        content_types=[],
        query_tags=list(payload.query_tags),
        date_from=payload.date_from,
        date_to=payload.date_to,
    )
    return [
        NoteSearchMatch(
            path=item.doc.path,
            owner_person_id=item.doc.owner_person_id,
            visibility_scope=item.doc.visibility_scope,
            item_type=item.doc.item_type,  # type: ignore[arg-type]
            role=item.doc.role,  # type: ignore[arg-type]
            title=item.doc.title,
            summary=item.doc.summary,
            excerpt=_excerpt_for_doc(item.doc),
            content=_content_for_doc(item.doc, include_content=payload.include_content),
            content_type=item.doc.content_type,
            source_date=item.doc.source_date,
            size_bytes=item.doc.size_bytes,
            etag=item.doc.etag,
            file_id=item.doc.provider_file_id,
            tags=list(item.doc.tags_jsonb or []),
            nextcloud_url=item.doc.nextcloud_url,
            raw_note_url=item.doc.raw_note_url,
            related_paths=list(item.doc.related_paths_jsonb or []),
            source_refs=_refs(item.source_refs),
            score=item.score,
            match_reasons=item.reasons,
        )
        for item in ranked
    ]


def search_all(db: Session, *, payload: UnifiedSearchRequest) -> list[UnifiedSearchMatch]:
    ranked = search_documents(
        db,
        family_id=payload.family_id,
        owner_person_id=payload.owner_person_id,
        query_text=payload.query,
        top_k=payload.top_k,
        document_kinds=list(payload.document_kinds or ["file", "note"]),
        preferred_item_types=list(payload.preferred_item_types),
        content_types=list(payload.content_types),
        query_tags=list(payload.query_tags),
        date_from=payload.date_from,
        date_to=payload.date_to,
    )
    return [
        UnifiedSearchMatch(
            doc_id=str(item.doc.doc_id),
            document_kind=item.doc.document_kind,  # type: ignore[arg-type]
            path=item.doc.path,
            title=item.doc.title,
            name=item.doc.name,
            item_type=item.doc.item_type,
            role=item.doc.role,
            summary=item.doc.summary,
            excerpt=_excerpt_for_doc(item.doc),
            content=_content_for_doc(item.doc, include_content=payload.include_content),
            content_type=item.doc.content_type,
            media_kind=item.doc.media_kind,
            source_date=item.doc.source_date,
            size_bytes=item.doc.size_bytes,
            etag=item.doc.etag,
            file_id=item.doc.provider_file_id,
            nextcloud_url=item.doc.nextcloud_url,
            raw_note_url=item.doc.raw_note_url,
            related_paths=list(item.doc.related_paths_jsonb or []),
            source_refs=_refs(item.source_refs),
            tags=list(item.doc.tags_jsonb or []),
            score=item.score,
            ingestion_status=item.doc.ingestion_status,
            match_reasons=item.reasons,
        )
        for item in ranked
    ]
