#!/usr/bin/env python3
from __future__ import annotations

import base64
import os
import posixpath
import re
from typing import Any

from agents.note_agent.agent import _extract_raw_note_url, _extract_section, _extract_tags, _nextcloud_files_app_url
from agents.note_agent.document_extractors import can_extract_extension, extract_document_bytes
from agents.note_agent.retrieval_client import NoteRetrievalClient
from agents.note_agent.settings import note_settings
from agents.note_agent.tools import NextcloudNotesTool


def _walk(tools: NextcloudNotesTool, path: str) -> list[dict[str, Any]]:
    listing = tools.list_directory(path)
    files: list[dict[str, Any]] = []
    for item in listing.get("files", []):
        child_path = str(item.get("path") or "")
        if not child_path:
            continue
        if item.get("is_directory"):
            files.extend(_walk(tools, child_path))
        else:
            files.append(item)
    return files


def _read_text(tools: NextcloudNotesTool, path: str, content_type: str) -> tuple[str | None, str | None]:
    payload = tools.read(path)
    content = payload.get("content") or payload.get("text")
    if not isinstance(content, str):
        return None, payload.get("content_type") or content_type
    if payload.get("encoding") == "base64":
        extension = posixpath.splitext(path)[1].lower()
        if not can_extract_extension(extension):
            return None, payload.get("content_type") or content_type
        extracted = extract_document_bytes(base64.b64decode(content), extension)
        return extracted.text, payload.get("content_type") or content_type
    return content, payload.get("content_type") or content_type


def _infer_item_type(path: str) -> tuple[str, str]:
    if "/Archive/Raw/" in path:
        return "raw", "archive"
    if "/Inbox/Attachments/" in path:
        return "attachment", "attachment"
    return "polished", "polished"


def main() -> int:
    actor = os.environ.get("NOTE_REINDEX_ACTOR", "").strip()
    family_id = int(os.environ.get("NOTE_REINDEX_FAMILY_ID", "0"))
    if not actor or family_id <= 0:
        raise SystemExit("Set NOTE_REINDEX_ACTOR and NOTE_REINDEX_FAMILY_ID before running.")

    tools = NextcloudNotesTool()
    client = NoteRetrievalClient()
    indexed = 0
    skipped = 0
    for item in _walk(tools, note_settings.note_agent_root):
        path = str(item.get("path") or "")
        if not path or path.endswith("/"):
            continue
        item_type, role = _infer_item_type(path)
        content_type = str(item.get("content_type") or "")
        text, resolved_type = _read_text(tools, path, content_type)
        if item_type == "attachment" and not text:
            skipped += 1
            continue
        title = posixpath.basename(path)
        summary = None
        excerpt = None
        tags: list[str] = []
        raw_note_url = None
        if text:
            title_match = re.search(r"^#\s+(.+)$", text, flags=re.MULTILINE)
            if title_match:
                title = title_match.group(1).strip()
            summary = _extract_section(text, "Summary") or None
            excerpt = _extract_section(text, "Key Points") or _extract_section(text, "Details") or text[:500]
            tags = _extract_tags(text)
            raw_note_url = _extract_raw_note_url(text)
        client.index_note(
            actor=actor,
            payload={
                "family_id": family_id,
                "actor": actor,
                "source_session_id": None,
                "path": path,
                "item_type": item_type,
                "role": role,
                "title": title,
                "summary": summary,
                "body_text": text,
                "excerpt_text": excerpt,
                "content_type": resolved_type or content_type or None,
                "source_date": None,
                "tags": tags,
                "nextcloud_url": _nextcloud_files_app_url(path),
                "raw_note_url": raw_note_url,
                "related_paths": [],
                "metadata": {"reindexed": True},
            },
        )
        indexed += 1
    print(f"indexed={indexed} skipped={skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
