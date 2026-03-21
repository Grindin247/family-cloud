from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import posixpath
import re
import subprocess
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx


logger = logging.getLogger(__name__)

CANONICAL_FOLDERS = ("Inbox", "Projects", "Areas", "Resources", "Archive", "Unfiled")
HOME_DASHBOARD_DOC_RE = re.compile(r"^Family Cloud Doc \d{4}-\d{2}-\d{2} \d{2}-\d{2}-\d{2}\.md$")
GENERIC_NAME_RE = re.compile(
    r"^(?:untitled|new(?:[-_ ]doc(?:ument)?)?|document|doc|note|notes|whiteboard|image|photo|scan|file)(?:[-_ ]\d+)?$",
    re.IGNORECASE,
)
TEXT_EXTENSIONS = {
    ".md",
    ".markdown",
    ".txt",
    ".rtf",
    ".json",
    ".csv",
    ".tsv",
    ".log",
    ".yaml",
    ".yml",
    ".xml",
    ".html",
    ".htm",
}
NOTE_EXTENSIONS = {".md", ".markdown", ".txt"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".heic", ".heif", ".tif", ".tiff", ".bmp"}
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav", ".aac", ".flac", ".ogg"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}
PROJECT_KEYWORDS = {
    "project",
    "proposal",
    "estimate",
    "remodel",
    "renovation",
    "launch",
    "build",
    "milestone",
    "trip",
    "event",
    "party",
    "plan",
}
AREA_KEYWORDS = {
    "school",
    "church",
    "home",
    "health",
    "finance",
    "budget",
    "meal",
    "routine",
    "kids",
    "family",
    "calendar",
    "medical",
}
ARCHIVE_KEYWORDS = {
    "archive",
    "receipt",
    "invoice",
    "statement",
    "bill",
    "tax",
    "warranty",
    "insurance",
    "record",
    "completed",
    "closed",
    "old",
}
RESOURCE_KEYWORDS = {
    "guide",
    "reference",
    "manual",
    "template",
    "checklist",
    "recipe",
    "notes",
    "ideas",
    "resources",
    "howto",
}
FILE_AGENT_TIMEOUT_SECONDS = int(os.environ.get("FILE_AGENT_INBOX_TIMEOUT_SECONDS", "180"))
FILE_AGENT_MAX_TEXT_CHARS = int(os.environ.get("FILE_AGENT_INBOX_MAX_TEXT_CHARS", "12000"))


def _normalize_path(path: str) -> str:
    clean = posixpath.normpath("/" + (path or "").strip().lstrip("/"))
    return "/" if clean in {"/.", "//"} else clean


def _base_name(path: str) -> str:
    return posixpath.basename(path.rstrip("/"))


def _split_name(name: str) -> tuple[str, str]:
    stem, ext = posixpath.splitext(name)
    return stem or name, ext.lower()


def _strip_markdown_title(value: str) -> str:
    line = value.strip().lstrip("#").strip()
    return re.sub(r"\s+", " ", line)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:80].strip("-") or "file"


def _clean_space(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _looks_descriptive(stem: str) -> bool:
    cleaned = re.sub(r"^\d{4}-\d{2}-\d{2}[_-]\d{6}[_-]?", "", stem).strip(" -_")
    if not cleaned:
        return False
    if GENERIC_NAME_RE.match(cleaned):
        return False
    return len(re.findall(r"[a-z0-9]{3,}", cleaned.lower())) >= 2


def _parse_timestamp(value: str | None) -> datetime:
    if value:
        for parser in (
            lambda item: datetime.fromisoformat(item.replace("Z", "+00:00")),
            parsedate_to_datetime,
        ):
            try:
                parsed = parser(value)
                if parsed.tzinfo is None:
                    return parsed.replace(tzinfo=UTC)
                return parsed.astimezone(UTC)
            except Exception:
                continue
    return datetime.now(UTC)


def _extract_text_from_bytes(raw: bytes, content_type: str | None, extension: str) -> str | None:
    lowered_type = (content_type or "").lower()
    text_like = lowered_type.startswith("text/") or "json" in lowered_type or "xml" in lowered_type
    if not text_like and extension not in TEXT_EXTENSIONS:
        return None
    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            decoded = raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        normalized = decoded.replace("\x00", "").strip()
        if normalized:
            return normalized
    return None


def _extract_title(text: str | None, stem: str) -> str:
    if text:
        for line in text.splitlines():
            candidate = _strip_markdown_title(line)
            if len(candidate) < 4:
                continue
            if candidate.lower() in {"inbox", "notes"}:
                continue
            return candidate[:120]
    return stem.replace("-", " ").replace("_", " ").strip()


def _score_keywords(corpus: str, keywords: set[str]) -> int:
    return sum(1 for keyword in keywords if keyword in corpus)


def _folder_from_corpus(corpus: str) -> tuple[str, str]:
    scores = {
        "Archive": _score_keywords(corpus, ARCHIVE_KEYWORDS),
        "Projects": _score_keywords(corpus, PROJECT_KEYWORDS),
        "Areas": _score_keywords(corpus, AREA_KEYWORDS),
        "Resources": _score_keywords(corpus, RESOURCE_KEYWORDS),
    }
    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    if not ordered or ordered[0][1] <= 0:
        return "Resources", "fallback-resource-default"
    folder, score = ordered[0]
    return folder, f"keyword-score:{folder.lower()}={score}"


def infer_file_item_type(content_type: str | None, extension: str, readable_text: str | None) -> str:
    lowered = (content_type or "").lower()
    if lowered.startswith("image/") or extension in IMAGE_EXTENSIONS:
        return "image"
    if lowered.startswith("audio/") or extension in AUDIO_EXTENSIONS:
        return "audio"
    if lowered.startswith("video/") or extension in VIDEO_EXTENSIONS:
        return "video"
    if readable_text:
        if extension in NOTE_EXTENSIONS:
            return "note"
        return "document"
    if extension in {".zip", ".tar", ".gz", ".7z", ".rar"}:
        return "archive"
    return "other"


def infer_file_role(folder: str) -> str:
    if folder == "Archive":
        return "archive"
    if folder == "Unfiled":
        return "inbox"
    return "filed"


def infer_note_role(folder: str) -> str:
    if folder == "Archive":
        return "archive"
    return "polished"


@dataclass
class FileAgentInboxDecision:
    folder: str
    title: str
    filename_slug: str
    summary: str
    key_insights: list[str]
    actions: list[str]
    open_questions: list[str]
    rewritten_markdown: str
    confidence: float
    reason: str


def derive_filing_decision(
    *,
    path: str,
    content_type: str | None,
    readable_text: str | None,
    timestamp: datetime,
    source_kind: str = "ready-tag",
) -> dict[str, Any]:
    original_name = _base_name(path)
    stem, extension = _split_name(original_name)
    descriptive_name = _looks_descriptive(stem)
    readable = bool(readable_text and readable_text.strip())
    if source_kind == "dashboard-doc":
        folder, folder_reason = _folder_from_corpus(" ".join(filter(None, [stem.lower(), (readable_text or "").lower()])))
        title = _extract_title(readable_text, "captured-note")
        confidence = 0.9 if readable else 0.72
        reason = f"dashboard-doc:{folder_reason}"
    elif not readable and not descriptive_name:
        folder = "Unfiled"
        title = "unfiled"
        confidence = 0.2
        reason = "generic-name-without-readable-text"
    else:
        folder, folder_reason = _folder_from_corpus(" ".join(filter(None, [stem.lower(), (readable_text or "").lower(), (content_type or "").lower()])))
        title = _extract_title(readable_text, stem if descriptive_name else "captured-file")
        confidence = 0.55
        if readable:
            confidence += 0.2
        if descriptive_name:
            confidence += 0.1
        if folder != "Resources":
            confidence += 0.1
        reason = folder_reason
    timestamp_prefix = timestamp.astimezone(UTC).strftime("%Y-%m-%d_%H%M%S")
    slug = _slugify(title if readable or descriptive_name else "unfiled")
    filename = f"{timestamp_prefix}_{slug}{extension}"
    return {
        "folder": folder,
        "filename": filename,
        "title": title,
        "readable": readable,
        "descriptive_name": descriptive_name,
        "confidence": round(min(confidence, 0.99), 2),
        "reason": reason,
    }


def _sanitize_lines(values: Any, *, limit: int = 5, fallback: str | None = None) -> list[str]:
    items: list[str] = []
    raw_values = values if isinstance(values, list) else []
    for raw in raw_values:
        if not isinstance(raw, str):
            continue
        cleaned = _clean_space(raw.lstrip("-*0123456789. \t"))
        if len(cleaned) < 3:
            continue
        if cleaned not in items:
            items.append(cleaned[:280])
        if len(items) >= limit:
            break
    if items or fallback is None:
        return items
    return [fallback]


def _build_structured_note_markdown(
    *,
    title: str,
    summary: str,
    key_insights: list[str],
    actions: list[str],
    open_questions: list[str],
    raw_note_content: str,
) -> str:
    lines = [f"# {title}", "", "## Summary", "", summary, "", "## Key Insights", ""]
    if key_insights:
        lines.extend(f"- {item}" for item in key_insights)
    else:
        lines.append("- No high-confidence insights were identified yet.")
    lines.extend(["", "## Actions", ""])
    if actions:
        lines.extend(f"- {item}" for item in actions)
    else:
        lines.append("- No clear action items were identified.")
    lines.extend(["", "## Open Questions", ""])
    if open_questions:
        lines.extend(f"- {item}" for item in open_questions)
    else:
        lines.append("- No open questions were identified.")
    lines.extend(["", "## Raw Note Content", "", raw_note_content.strip() or "(empty note)"])
    return "\n".join(lines).strip() + "\n"


def _file_agent_prompt(
    *,
    path: str,
    source_kind: str,
    original_name: str,
    extension: str,
    content_type: str | None,
    readable_text: str,
    timestamp: datetime,
) -> str:
    payload = {
        "source_path": path,
        "source_kind": source_kind,
        "original_filename": original_name,
        "original_extension": extension,
        "content_type": content_type or "",
        "source_timestamp_utc": timestamp.astimezone(UTC).isoformat(),
        "readable_text": readable_text[:FILE_AGENT_MAX_TEXT_CHARS],
    }
    return (
        "Analyze this inbox note for filing only. "
        "Do not read or write files, do not call MCP tools, do not queue items, and do not perform any side effects. "
        "Use only the note text included below.\n\n"
        "Return exactly one JSON object with these keys:\n"
        "folder, title, filename_slug, summary, key_insights, actions, open_questions, rewritten_markdown, confidence, reason.\n\n"
        "Rules:\n"
        "- folder must be one of Projects, Areas, Resources, Archive, Unfiled.\n"
        "- filename_slug must be short, semantic, and durable. Do not include timestamps or file extensions.\n"
        "- summary must be meaningful prose, not a copied first sentence.\n"
        "- key_insights, actions, and open_questions must be short lists of strings.\n"
        "- If the note is too ambiguous to classify confidently, use folder Unfiled and explain why.\n"
        "- Do not invent facts not present in the note.\n"
        "- rewritten_markdown may be included, but the structured fields are the source of truth.\n\n"
        f"Input JSON:\n{json.dumps(payload, ensure_ascii=True)}"
    )


def _parse_file_agent_result(raw: dict[str, Any], readable_text: str) -> FileAgentInboxDecision:
    folder = str(raw.get("folder") or "Unfiled")
    if folder not in {"Projects", "Areas", "Resources", "Archive", "Unfiled"}:
        folder = "Unfiled"
    title = _clean_space(str(raw.get("title") or ""))[:120] or "Inbox Note"
    slug_source = _clean_space(str(raw.get("filename_slug") or "")) or title
    filename_slug = _slugify(slug_source)
    summary = _clean_space(str(raw.get("summary") or ""))[:500] or "Captured note needs a quick human review."
    key_insights = _sanitize_lines(raw.get("key_insights"), fallback="No high-confidence insights were identified yet.")
    actions = _sanitize_lines(raw.get("actions"))
    open_questions = _sanitize_lines(raw.get("open_questions"))
    rewritten_markdown = _build_structured_note_markdown(
        title=title,
        summary=summary,
        key_insights=key_insights,
        actions=actions,
        open_questions=open_questions,
        raw_note_content=readable_text,
    )
    try:
        confidence = float(raw.get("confidence"))
    except Exception:
        confidence = 0.45
    reason = _clean_space(str(raw.get("reason") or ""))[:280] or "file-agent-generated"
    return FileAgentInboxDecision(
        folder=folder,
        title=title,
        filename_slug=filename_slug,
        summary=summary,
        key_insights=key_insights,
        actions=actions,
        open_questions=open_questions,
        rewritten_markdown=rewritten_markdown,
        confidence=max(0.0, min(confidence, 0.99)),
        reason=reason,
    )


def _invoke_file_agent_json(*, prompt: str, timeout_seconds: int) -> dict[str, Any]:
    command = [
        "openclaw",
        "agent",
        "--agent",
        "file-agent",
        "--message",
        prompt,
        "--json",
        "--timeout",
        str(timeout_seconds),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=timeout_seconds + 10)
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or "openclaw agent failed").strip())
    payload = json.loads(completed.stdout)
    result = payload.get("result") or {}
    items = result.get("payloads") or []
    for item in items:
        text = item.get("text")
        if not isinstance(text, str):
            continue
        stripped = text.strip()
        if not stripped:
            continue
        return json.loads(stripped)
    raise RuntimeError("FileAgent returned no JSON payload")


def synthesize_note_with_file_agent(
    *,
    path: str,
    content_type: str | None,
    readable_text: str,
    timestamp: datetime,
    source_kind: str,
) -> FileAgentInboxDecision:
    original_name = _base_name(path)
    _, extension = _split_name(original_name)
    prompt = _file_agent_prompt(
        path=path,
        source_kind=source_kind,
        original_name=original_name,
        extension=extension,
        content_type=content_type,
        readable_text=readable_text,
        timestamp=timestamp,
    )
    raw = _invoke_file_agent_json(prompt=prompt, timeout_seconds=FILE_AGENT_TIMEOUT_SECONDS)
    return _parse_file_agent_result(raw, readable_text)


@dataclass
class InboxCandidate:
    path: str
    name: str
    size: int
    content_type: str
    last_modified: str | None
    etag: str | None
    file_id: str | None
    lock_owner: str | None = None
    source_kind: str = "ready-tag"


@dataclass
class ProcessingResult:
    source_path: str
    destination_path: str
    title: str
    folder: str
    item_type: str
    confidence: float
    indexed: bool
    unreadable: bool
    reason: str
    nextcloud_url: str | None


def _tool_payload(result: Any) -> dict[str, Any]:
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        return structured
    content = getattr(result, "content", None)
    text_fragments: list[str] = []
    if isinstance(content, list):
        for item in content:
            text = getattr(item, "text", None)
            if isinstance(text, str):
                stripped = text.strip()
                if stripped:
                    text_fragments.append(stripped)
                try:
                    decoded = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
                if isinstance(decoded, dict):
                    return decoded
    if bool(getattr(result, "isError", False)):
        raise RuntimeError(" ".join(text_fragments) or "MCP tool returned an error")
    raise RuntimeError("MCP tool returned no structured payload")


class McpNextcloudClient:
    def __init__(self, url: str) -> None:
        self.url = url
        self._transport_cm: Any | None = None
        self._session_cm: Any | None = None
        self.session: Any | None = None

    async def __aenter__(self) -> "McpNextcloudClient":
        from mcp.client.session import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        self._transport_cm = streamablehttp_client(self.url)
        read_stream, write_stream, _ = await self._transport_cm.__aenter__()
        self._session_cm = ClientSession(read_stream, write_stream)
        self.session = await self._session_cm.__aenter__()
        await self.session.initialize()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self._session_cm is not None:
            await self._session_cm.__aexit__(exc_type, exc, tb)
        if self._transport_cm is not None:
            await self._transport_cm.__aexit__(exc_type, exc, tb)

    async def _call_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        assert self.session is not None
        result = await self.session.call_tool(name, args)
        return _tool_payload(result)

    async def list_ready_files(self, scope: str, tag_name: str) -> list[InboxCandidate]:
        payload = await self._call_tool("nc_webdav_list_ready_files", {"scope": scope, "tag_name": tag_name})
        items = payload.get("results") or []
        candidates: list[InboxCandidate] = []
        for item in items:
            if item.get("is_directory"):
                continue
            candidates.append(
                InboxCandidate(
                    path=str(item.get("path") or ""),
                    name=str(item.get("name") or _base_name(str(item.get("path") or ""))),
                    size=int(item.get("size") or 0),
                    content_type=str(item.get("content_type") or ""),
                    last_modified=item.get("last_modified"),
                    etag=str(item.get("etag") or "") or None,
                    file_id=str(item.get("file_id") or "") or None,
                    lock_owner=str(item.get("lock_owner") or "") or None,
                    source_kind="ready-tag",
                )
            )
        return candidates

    async def list_directory(self, path: str) -> list[dict[str, Any]]:
        try:
            payload = await self._call_tool("nc_webdav_list_directory_detailed", {"path": path})
            return list(payload.get("files") or [])
        except Exception:
            payload = await self._call_tool("nc_webdav_list_directory", {"path": path})
            return list(payload.get("files") or [])

    async def read_file(self, path: str) -> dict[str, Any]:
        return await self._call_tool("nc_webdav_read_file", {"path": path})

    async def read_raw_file(self, path: str) -> dict[str, Any]:
        return await self._call_tool("nc_webdav_read_file_raw", {"path": path})

    async def create_directory(self, path: str) -> None:
        await self._call_tool("nc_webdav_create_directory", {"path": path})

    async def move_resource(self, source_path: str, destination_path: str) -> None:
        payload = await self._call_tool(
            "nc_webdav_move_resource",
            {"source_path": source_path, "destination_path": destination_path, "overwrite": False},
        )
        status_code = int(payload.get("status_code") or 0)
        if status_code == 412:
            raise FileExistsError(destination_path)

    async def write_file(self, path: str, content: str, *, content_type: str | None = None) -> None:
        await self._call_tool("nc_webdav_write_file", {"path": path, "content": content, "content_type": content_type})

    async def remove_tag_from_file(self, file_id: str | None, tag_name: str) -> None:
        if not file_id:
            return
        try:
            await self._call_tool("nc_webdav_remove_tag_from_file", {"file_id": file_id, "tag_name": tag_name})
        except Exception:
            return


def _decode_read_payload(payload: dict[str, Any], extension: str) -> tuple[str | None, bytes | None, str]:
    content_type = str(payload.get("content_type") or "")
    content = payload.get("content")
    if not isinstance(content, str):
        return None, None, content_type
    if payload.get("encoding") == "base64":
        raw = base64.b64decode(content)
        return _extract_text_from_bytes(raw, content_type, extension), raw, content_type
    return content.strip() or None, None, content_type


async def _extract_readable_text(client: McpNextcloudClient, candidate: InboxCandidate) -> tuple[str | None, str]:
    _, extension = _split_name(candidate.name)
    content_type = candidate.content_type
    try:
        payload = await client.read_file(candidate.path)
        readable_text, _, parsed_content_type = _decode_read_payload(payload, extension)
        if parsed_content_type:
            content_type = parsed_content_type
        if readable_text:
            return readable_text, content_type
    except Exception:
        pass
    try:
        raw_payload = await client.read_raw_file(candidate.path)
        raw_bytes = base64.b64decode(str(raw_payload.get("content") or ""))
        content_type = str(raw_payload.get("content_type") or content_type)
        return _extract_text_from_bytes(raw_bytes, content_type, extension), content_type
    except Exception:
        return None, content_type


def _build_nextcloud_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/apps/files/files{quote(_normalize_path(path), safe='/')}"


@lru_cache(maxsize=1)
def _load_repo_env() -> dict[str, str]:
    root = Path(__file__).resolve().parents[2]
    env_file = root / ".env"
    if not env_file.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def default_nextcloud_base_url() -> str:
    explicit = (os.environ.get("NEXTCLOUD_BASE_URL") or "").strip()
    if explicit:
        return explicit.rstrip("/")
    repo_env = _load_repo_env()
    explicit = (repo_env.get("NEXTCLOUD_BASE_URL") or "").strip()
    if explicit:
        return explicit.rstrip("/")
    family_domain = (
        os.environ.get("NEXT_PUBLIC_FAMILY_DOMAIN")
        or os.environ.get("FAMILY_DOMAIN")
        or repo_env.get("NEXT_PUBLIC_FAMILY_DOMAIN")
        or repo_env.get("FAMILY_DOMAIN")
        or ""
    ).strip()
    if family_domain:
        return f"https://nextcloud.{family_domain}"
    return "https://nextcloud.local"


async def _ensure_directory(client: McpNextcloudClient, path: str) -> None:
    normalized = _normalize_path(path)
    if normalized == "/":
        return
    current = ""
    for segment in normalized.strip("/").split("/"):
        current += "/" + segment
        await client.create_directory(current)


async def _path_exists(client: McpNextcloudClient, path: str) -> bool:
    normalized = _normalize_path(path)
    if normalized == "/":
        return True
    parent = posixpath.dirname(normalized) or "/"
    basename = _base_name(normalized)
    entries = await client.list_directory(parent)
    for entry in entries:
        item_path = _normalize_path(str(entry.get("path") or ""))
        item_name = str(entry.get("name") or _base_name(item_path))
        if item_path == normalized or item_name == basename:
            return True
    return False


async def _unique_destination(client: McpNextcloudClient, destination_path: str) -> str:
    normalized = _normalize_path(destination_path)
    parent = posixpath.dirname(normalized) or "/"
    stem, ext = _split_name(_base_name(normalized))
    candidate = normalized
    counter = 2
    while await _path_exists(client, candidate):
        candidate = f"{parent}/{stem}-{counter}{ext}"
        counter += 1
    return candidate


def _as_file_entry(item: dict[str, Any]) -> InboxCandidate | None:
    if bool(item.get("is_directory", False)):
        return None
    path = str(item.get("path") or "")
    return InboxCandidate(
        path=path,
        name=str(item.get("name") or _base_name(path)),
        size=int(item.get("size") or 0),
        content_type=str(item.get("content_type") or ""),
        last_modified=item.get("last_modified"),
        etag=str(item.get("etag") or "") or None,
        file_id=str(item.get("file_id") or "") or None,
        lock_owner=str(item.get("lock_owner") or item.get("lock_owner_display_name") or "") or None,
        source_kind="listing",
    )


async def discover_candidates(
    client: McpNextcloudClient,
    *,
    ready_tag: str,
    include_dashboard_docs: bool,
    idle_minutes: int,
) -> tuple[list[InboxCandidate], int, int]:
    try:
        ready_candidates = await client.list_ready_files("/Notes/Inbox", ready_tag)
    except Exception as exc:
        logger.warning("ready_tag_lookup_failed scope=/Notes/Inbox tag=%s error=%s", ready_tag, exc)
        ready_candidates = []
    by_path = {item.path: item for item in ready_candidates}
    skipped_locked = 0
    skipped_recent = 0
    entries = await client.list_directory("/Notes/Inbox")
    for item in entries:
        entry = _as_file_entry(item)
        if entry is None:
            continue
        existing = by_path.get(entry.path)
        if existing is not None and entry.lock_owner:
            existing.lock_owner = entry.lock_owner
    for path, item in list(by_path.items()):
        if item.lock_owner:
            skipped_locked += 1
            by_path.pop(path, None)
    if include_dashboard_docs:
        cutoff = datetime.now(UTC) - timedelta(minutes=max(1, idle_minutes))
        for item in entries:
            entry = _as_file_entry(item)
            if entry is None:
                continue
            if not HOME_DASHBOARD_DOC_RE.match(entry.name):
                continue
            if entry.path in by_path:
                continue
            if entry.size <= 0:
                skipped_recent += 1
                continue
            if entry.lock_owner:
                skipped_locked += 1
                continue
            modified_at = _parse_timestamp(entry.last_modified)
            if modified_at > cutoff:
                skipped_recent += 1
                continue
            entry.source_kind = "dashboard-doc"
            by_path[entry.path] = entry
    return list(by_path.values()), skipped_locked, skipped_recent


def _source_date(candidate: InboxCandidate) -> str | None:
    if not candidate.last_modified:
        return None
    return _parse_timestamp(candidate.last_modified).date().isoformat()


def _source_ref(title: str, destination_path: str, nextcloud_url: str) -> dict[str, Any]:
    return {
        "type": "nextcloud_file",
        "title": title,
        "path": destination_path,
        "url": nextcloud_url,
    }


def _memory_text(title: str, summary: str, destination_path: str, nextcloud_url: str, key_insights: list[str]) -> str:
    lines = [
        f"Title: {title}",
        f"Path: {destination_path}",
        f"URL: {nextcloud_url}",
        "",
        "Summary:",
        summary,
    ]
    if key_insights:
        lines.extend(["", "Key insights:"])
        lines.extend(f"- {item}" for item in key_insights[:5])
    return "\n".join(lines).strip()


def _http_headers(actor: str) -> dict[str, str]:
    return {"X-Dev-User": actor}


def _verify_for_url(url: str) -> bool:
    return not url.startswith("https://")


def _index_document(
    *,
    decision_api_base_url: str,
    actor: str,
    family_id: int,
    candidate: InboxCandidate,
    destination_path: str,
    folder: str,
    readable_text: str | None,
    content_type: str,
    title: str,
    confidence: float,
    reason: str,
    rewritten_content: str | None,
    nextcloud_url: str,
    summary: str | None,
    key_insights: list[str],
    source_kind: str,
) -> bool:
    _, ext = _split_name(destination_path)
    payload_base = {
        "family_id": family_id,
        "actor": actor,
        "source_session_id": "nextcloud-file-agent",
        "path": destination_path,
        "tags": ["ready-processed", folder.lower(), source_kind],
        "nextcloud_url": nextcloud_url,
        "related_paths": [candidate.path],
        "metadata": {
            "source_path": candidate.path,
            "destination_folder": folder,
            "source_file_id": candidate.file_id,
            "file_agent": "shared_inbox_processor",
            "confidence": confidence,
            "filing_reason": reason,
            "source_kind": source_kind,
        },
    }
    try:
        with httpx.Client(timeout=30.0, verify=_verify_for_url(decision_api_base_url)) as client:
            if (rewritten_content or readable_text) and ext in NOTE_EXTENSIONS:
                response = client.post(
                    f"{decision_api_base_url.rstrip('/')}/notes/index",
                    headers=_http_headers(actor),
                    json={
                        **payload_base,
                        "item_type": "polished",
                        "role": infer_note_role(folder),
                        "title": title,
                        "summary": summary or (readable_text or "")[:280] or None,
                        "body_text": (rewritten_content or readable_text or "")[:16000],
                        "excerpt_text": (summary or readable_text or "")[:500] or None,
                        "content_type": content_type or "text/markdown",
                        "source_date": _source_date(candidate),
                        "raw_note_url": None,
                    },
                )
            else:
                response = client.post(
                    f"{decision_api_base_url.rstrip('/')}/files/index",
                    headers=_http_headers(actor),
                    json={
                        **payload_base,
                        "name": _base_name(destination_path),
                        "item_type": infer_file_item_type(content_type, ext, readable_text),
                        "role": infer_file_role(folder),
                        "title": title,
                        "summary": summary or (readable_text[:280] if readable_text else None),
                        "body_text": readable_text[:4000] if readable_text else None,
                        "excerpt_text": (summary or readable_text or "")[:500] or None,
                        "content_type": content_type or None,
                        "size_bytes": candidate.size,
                        "etag": candidate.etag,
                        "file_id": candidate.file_id,
                        "source_date": _source_date(candidate),
                    },
                )
            response.raise_for_status()
            if summary and confidence >= 0.7 and infer_file_item_type(content_type, ext, readable_text) in {"note", "document"}:
                client.post(
                    f"{decision_api_base_url.rstrip('/')}/family/{family_id}/memory/documents",
                    headers=_http_headers(actor),
                    json={
                        "family_id": family_id,
                        "type": "note",
                        "text": _memory_text(title, summary, destination_path, nextcloud_url, key_insights),
                        "owner_person_id": None,
                        "visibility_scope": "family",
                        "source_refs": [_source_ref(title, destination_path, nextcloud_url)],
                    },
                ).raise_for_status()
            return True
    except Exception:
        return False


def _create_file_question(
    *,
    decision_api_base_url: str,
    actor: str,
    family_id: int,
    candidate: InboxCandidate,
    destination_path: str,
    title: str,
    confidence: float,
    reason: str,
    nextcloud_url: str,
) -> None:
    try:
        with httpx.Client(timeout=20.0, verify=_verify_for_url(decision_api_base_url)) as client:
            client.post(
                f"{decision_api_base_url.rstrip('/')}/family/{family_id}/ops/questions",
                headers=_http_headers(actor),
                json={
                    "domain": "file",
                    "source_agent": "FileAgent",
                    "topic": f"Needs filing review: {title}",
                    "summary": "Low-confidence inbox filing result needs a human check.",
                    "prompt": (
                        f"FileAgent moved `{candidate.path}` to `{destination_path}` with low confidence "
                        f"({confidence:.2f}). Reason: {reason}. Please confirm the final destination."
                    ),
                    "urgency": "medium",
                    "topic_type": "filing_review",
                    "answer_sufficiency_state": "needed",
                    "dedupe_key": f"file-filing-review:{destination_path}",
                    "context": {
                        "source_path": candidate.path,
                        "destination_path": destination_path,
                        "file_id": candidate.file_id,
                        "confidence": confidence,
                        "reason": reason,
                        "nextcloud_url": nextcloud_url,
                    },
                    "artifact_refs": [{"type": "file", "path": destination_path}],
                },
            ).raise_for_status()
    except Exception:
        return


def _default_status(processed: int, conflicts: list[dict[str, Any]]) -> str:
    if processed > 0:
        return "completed"
    if conflicts:
        return "partial"
    return "completed"


async def process_inbox_async(
    *,
    mcp_url: str,
    ready_tag: str,
    decision_api_base_url: str,
    actor: str,
    family_id: int,
    nextcloud_base_url: str | None = None,
    include_dashboard_docs: bool = True,
    dashboard_idle_minutes: int = 10,
    confidence_threshold: float = 0.7,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "status": "completed",
        "processed": 0,
        "indexed": 0,
        "unfiled": 0,
        "skipped_locked": 0,
        "skipped_recent": 0,
        "conflicts": [],
        "results": [],
    }
    nextcloud_url_base = (nextcloud_base_url or default_nextcloud_base_url()).rstrip("/")
    async with McpNextcloudClient(mcp_url) as client:
        for folder in CANONICAL_FOLDERS:
            await _ensure_directory(client, f"/Notes/{folder}")
        candidates, skipped_locked, skipped_recent = await discover_candidates(
            client,
            ready_tag=ready_tag,
            include_dashboard_docs=include_dashboard_docs,
            idle_minutes=dashboard_idle_minutes,
        )
        summary["skipped_locked"] = skipped_locked
        summary["skipped_recent"] = skipped_recent
        for candidate in candidates:
            readable_text, content_type = await _extract_readable_text(client, candidate)
            timestamp = _parse_timestamp(candidate.last_modified)
            decision = derive_filing_decision(
                path=candidate.path,
                content_type=content_type,
                readable_text=readable_text,
                timestamp=timestamp,
                source_kind=candidate.source_kind,
            )
            rewritten_content: str | None = None
            summary_text: str | None = None
            key_insights: list[str] = []
            if readable_text and infer_file_item_type(content_type, _split_name(candidate.name)[1], readable_text) in {"note", "document"}:
                try:
                    ai_decision = synthesize_note_with_file_agent(
                        path=candidate.path,
                        content_type=content_type,
                        readable_text=readable_text,
                        timestamp=timestamp,
                        source_kind=candidate.source_kind,
                    )
                    filename = f"{timestamp.astimezone(UTC).strftime('%Y-%m-%d_%H%M%S')}_{ai_decision.filename_slug}{_split_name(candidate.name)[1]}"
                    decision = {
                        "folder": ai_decision.folder,
                        "filename": filename,
                        "title": ai_decision.title,
                        "readable": True,
                        "descriptive_name": True,
                        "confidence": ai_decision.confidence,
                        "reason": ai_decision.reason,
                    }
                    rewritten_content = ai_decision.rewritten_markdown
                    summary_text = ai_decision.summary
                    key_insights = ai_decision.key_insights
                except Exception as exc:
                    logger.warning("file_agent_note_synthesis_failed path=%s error=%s", candidate.path, exc)
                    fallback_title = _extract_title(readable_text, _split_name(candidate.name)[0] or "captured-note")
                    decision = {
                        "folder": "Unfiled",
                        "filename": f"{timestamp.astimezone(UTC).strftime('%Y-%m-%d_%H%M%S')}_{_slugify(fallback_title)}{_split_name(candidate.name)[1]}",
                        "title": fallback_title,
                        "readable": True,
                        "descriptive_name": True,
                        "confidence": 0.2,
                        "reason": "file-agent-synthesis-failed",
                    }
            folder = str(decision["folder"])
            if float(decision["confidence"]) < confidence_threshold:
                folder = "Unfiled"
            destination = await _unique_destination(client, f"/Notes/{folder}/{decision['filename']}")
            try:
                await client.move_resource(candidate.path, destination)
            except FileExistsError:
                summary["conflicts"].append({"source": candidate.path, "destination": destination})
                continue
            if rewritten_content:
                await client.write_file(destination, rewritten_content, content_type="text/markdown")
            await client.remove_tag_from_file(candidate.file_id, ready_tag)
            nextcloud_url = _build_nextcloud_url(nextcloud_url_base, destination)
            indexed = _index_document(
                decision_api_base_url=decision_api_base_url,
                actor=actor,
                family_id=family_id,
                candidate=candidate,
                destination_path=destination,
                folder=folder,
                readable_text=readable_text,
                content_type=content_type,
                title=str(decision["title"]),
                confidence=float(decision["confidence"]),
                reason=str(decision["reason"]),
                rewritten_content=rewritten_content,
                nextcloud_url=nextcloud_url,
                summary=summary_text,
                key_insights=key_insights,
                source_kind=candidate.source_kind,
            )
            if folder == "Unfiled":
                _create_file_question(
                    decision_api_base_url=decision_api_base_url,
                    actor=actor,
                    family_id=family_id,
                    candidate=candidate,
                    destination_path=destination,
                    title=str(decision["title"]),
                    confidence=float(decision["confidence"]),
                    reason=str(decision["reason"]),
                    nextcloud_url=nextcloud_url,
                )
            result = ProcessingResult(
                source_path=candidate.path,
                destination_path=destination,
                title=str(decision["title"]),
                folder=folder,
                item_type=infer_file_item_type(content_type, _split_name(destination)[1], rewritten_content or readable_text),
                confidence=float(decision["confidence"]),
                indexed=indexed,
                unreadable=not bool(readable_text),
                reason=str(decision["reason"]),
                nextcloud_url=nextcloud_url,
            )
            summary["processed"] += 1
            summary["indexed"] += int(indexed)
            summary["unfiled"] += int(folder == "Unfiled")
            summary["results"].append(asdict(result))
    summary["status"] = _default_status(summary["processed"], summary["conflicts"])
    return summary


def run_process_inbox(**kwargs: Any) -> dict[str, Any]:
    return asyncio.run(process_inbox_async(**kwargs))
