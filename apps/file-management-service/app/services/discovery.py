from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.common.file_inbox import (
    IMAGE_EXTENSIONS,
    McpNextcloudClient,
    NOTE_EXTENSIONS,
    TEXT_EXTENSIONS,
    _as_file_entry,
    _extract_readable_text,
    _extract_title,
    _normalize_path,
    _parse_timestamp,
    infer_file_item_type,
)
from app.core.config import settings
from app.models.documents import DiscoveryCursor
from app.services.decision_api import get_family_features
from app.services.documents import upsert_file_document
from app.schemas.files import FileIndexRequest

SPREADSHEET_EXTENSIONS = {".csv", ".tsv", ".xlsx", ".xls", ".ods"}
ARCHIVE_EXTENSIONS = {".zip", ".tar", ".gz", ".tgz", ".7z", ".rar"}
MEDIA_EXTENSIONS = {".mp3", ".m4a", ".wav", ".aac", ".flac", ".ogg", ".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}
SKIP_SEGMENTS = {"cache", ".cache", "thumbs", "thumbnails", "tmp", "temp", "node_modules", "vendor", "__pycache__"}


def _cursor(db: Session, *, family_id: int, root_path: str) -> DiscoveryCursor:
    row = db.execute(
        select(DiscoveryCursor).where(DiscoveryCursor.family_id == family_id, DiscoveryCursor.root_path == root_path)
    ).scalar_one_or_none()
    if row is None:
        row = DiscoveryCursor(family_id=family_id, root_path=root_path, status="idle")
        db.add(row)
        db.flush()
    return row


def _skip_path(path: str) -> bool:
    parts = {part.lower() for part in PurePosixPath(path).parts}
    return any(part in SKIP_SEGMENTS for part in parts)


def _extension(path: str) -> str:
    return PurePosixPath(path).suffix.lower()


def _extraction_profile(path: str, *, content_type: str | None, size: int | None) -> tuple[str, str]:
    ext = _extension(path)
    lowered_type = (content_type or "").lower()
    if _skip_path(path):
        return "skip", "skipped_noise"
    if ext in SPREADSHEET_EXTENSIONS or "spreadsheet" in lowered_type or "excel" in lowered_type:
        return "spreadsheet", "deferred"
    if ext in ARCHIVE_EXTENSIONS:
        return "archive", "indexed_metadata"
    if ext in MEDIA_EXTENSIONS or lowered_type.startswith(("audio/", "video/")):
        return "media", "indexed_metadata"
    if ext in IMAGE_EXTENSIONS or lowered_type.startswith("image/"):
        return "image", "deferred"
    if ext in NOTE_EXTENSIONS or ext in TEXT_EXTENSIONS or ext in {".pdf", ".docx", ".doc", ".odt", ".eml", ".html", ".htm", ".json", ".yaml", ".yml"}:
        if size is not None and size > settings.file_max_text_extract_bytes:
            return "text", "deferred"
        return "text", "indexed"
    return "metadata", "indexed_metadata"


async def _catalog_entry(client: McpNextcloudClient, db: Session, *, family_id: int, entry: dict[str, Any]) -> None:
    candidate = _as_file_entry(entry)
    if candidate is None:
        return
    profile, initial_status = _extraction_profile(candidate.path, content_type=candidate.content_type, size=candidate.size)
    readable_text = None
    content_type = candidate.content_type
    reliability = "missing"
    if profile in {"text", "spreadsheet"} and initial_status == "indexed":
        readable_text, content_type, reliability, _, _ = await _extract_readable_text(client, candidate)
    status = initial_status
    deferred_reason = None
    if profile in {"text", "spreadsheet"} and initial_status == "indexed" and not readable_text:
        if _extension(candidate.path) == ".pdf":
            status = "deferred"
            deferred_reason = "ocr_required"
        else:
            status = "indexed_metadata"
    item_type = infer_file_item_type(content_type, _extension(candidate.path), readable_text)
    title = _extract_title(readable_text, PurePosixPath(candidate.path).stem or "document")
    source_date = _parse_timestamp(candidate.last_modified).date() if candidate.last_modified else None
    modified_at = _parse_timestamp(candidate.last_modified) if candidate.last_modified else None
    payload = FileIndexRequest(
        family_id=family_id,
        actor="file-management-service",
        owner_person_id=None,
        visibility_scope="family",
        source_session_id="file-discovery-worker",
        source_agent_id="file-management-service",
        source_runtime="backend",
        path=_normalize_path(candidate.path),
        name=candidate.name,
        item_type=item_type,  # type: ignore[arg-type]
        role="filed" if "/Inbox/" not in candidate.path else "inbox",
        title=title,
        summary=(readable_text or "")[:280] or None,
        body_text=(readable_text or "")[: settings.file_max_body_chars] or None,
        excerpt_text=(readable_text or "")[: settings.file_max_excerpt_chars] or None,
        content_type=content_type or None,
        media_kind="text" if readable_text else (item_type if item_type in {"image", "audio", "video"} else None),
        source_date=source_date,
        modified_at=modified_at,
        size_bytes=candidate.size,
        etag=candidate.etag,
        file_id=candidate.file_id,
        is_directory=False,
        tags=[],
        nextcloud_url=None,
        related_paths=[],
        source_refs=[{"label": title, "path": candidate.path, "locator_type": "path", "locator_value": candidate.path}],
        metadata={
            "discovered_by": "file-worker",
            "extraction_profile": profile,
            "ingestion_status": status if reliability != "low" else "deferred",
            "reliability": reliability,
            "deferred_reason": deferred_reason,
        },
    )
    upsert_file_document(db, payload=payload)


async def scan_family_root_async(db: Session, *, family_id: int, root_path: str) -> dict[str, Any]:
    cursor = _cursor(db, family_id=family_id, root_path=root_path)
    cursor.status = "running"
    cursor.last_started_at = datetime.now(UTC)
    cursor.updated_at = datetime.now(UTC)
    item_count = 0
    async with McpNextcloudClient(settings.nextcloud_mcp_url) as client:
        stack = [root_path]
        while stack and item_count < settings.file_discovery_scan_limit:
            current = stack.pop()
            for item in await client.list_directory(current):
                if bool(item.get("is_directory")):
                    child = str(item.get("path") or "")
                    if child and not _skip_path(child):
                        stack.append(child)
                    continue
                await _catalog_entry(client, db, family_id=family_id, entry=item)
                item_count += 1
                if item_count >= settings.file_discovery_scan_limit:
                    break
    cursor.status = "completed"
    cursor.last_completed_at = datetime.now(UTC)
    cursor.last_item_count = item_count
    cursor.metadata_jsonb = {"scan_limit": settings.file_discovery_scan_limit}
    cursor.updated_at = datetime.now(UTC)
    return {"family_id": family_id, "root_path": root_path, "items": item_count}


def run_configured_discovery_scans(db: Session) -> dict[str, Any]:
    if not settings.file_discovery_enabled:
        return {"enabled": False, "runs": []}
    runs: list[dict[str, Any]] = []
    for family_id in settings.discovery_family_id_values:
        features = get_family_features(family_id=family_id, actor_email=None, internal_admin=True)
        files_enabled = next((bool(item.get("enabled")) for item in features if item.get("feature_key") == "files"), False)
        if not files_enabled:
            continue
        for root_path in settings.discovery_root_values:
            runs.append(asyncio.run(scan_family_root_async(db, family_id=family_id, root_path=root_path)))
    return {"enabled": True, "runs": runs}
