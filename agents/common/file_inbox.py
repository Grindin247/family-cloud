from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import posixpath
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from functools import lru_cache
import hashlib
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx


logger = logging.getLogger(__name__)

CANONICAL_FOLDERS = ("Inbox", "Projects", "Areas", "Resources", "Archive", "Unfiled")
MAX_FILE_AGENT_SUBFOLDER_DEPTH = 3
DEFAULT_SUBFOLDER_BY_FOLDER = {
    "Projects": "General",
    "Areas": "General",
    "Resources": "General",
    "Archive": "General",
}
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
FILE_AGENT_IMAGE_STAGING_DIR = Path(
    os.environ.get(
        "FILE_AGENT_IMAGE_STAGING_DIR",
        str(Path.home() / ".openclaw" / "workspace-file-agent" / "tmp" / "inbox-page-samples"),
    )
)
PARSER_PLACEHOLDER_PREFIXES = (
    "Document could not be parsed. Base64 content:",
    "Image could not be parsed. Base64 content:",
)


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


def _extract_page_image_paths(value: str | None) -> list[str]:
    text = value or ""
    return re.findall(r"!\[[^\]]*\]\((/tmp/pdf-images/[^)]+)\)", text)


def _sample_page_image_paths(paths: list[str], *, max_samples: int = 3) -> list[str]:
    if len(paths) <= max_samples:
        return paths
    indexes = sorted({0, len(paths) // 2, len(paths) - 1})
    return [paths[index] for index in indexes[:max_samples]]


def _staging_dir_for_source(source_path: str) -> Path:
    source_key = hashlib.sha1(source_path.encode("utf-8")).hexdigest()[:12]
    destination_dir = FILE_AGENT_IMAGE_STAGING_DIR / source_key
    destination_dir.mkdir(parents=True, exist_ok=True)
    return destination_dir


def _stage_page_image_paths(page_image_paths: list[str], *, source_path: str) -> list[str]:
    if not page_image_paths:
        return []
    destination_dir = _staging_dir_for_source(source_path)
    staged: list[str] = []
    for index, image_path in enumerate(page_image_paths):
        source = Path(image_path)
        if not source.exists():
            continue
        destination = destination_dir / f"page-{index}{source.suffix or '.png'}"
        if source.resolve() == destination.resolve():
            staged.append(str(destination))
            continue
        shutil.copy2(source, destination)
        staged.append(str(destination))
    return staged


def _pdf_page_samples(raw_pdf: bytes, *, source_path: str, max_samples: int = 3) -> list[str]:
    staging_dir = _staging_dir_for_source(source_path)
    pdf_path = staging_dir / "source.pdf"
    pdf_path.write_bytes(raw_pdf)

    try:
        completed = subprocess.run(
            ["pdfinfo", str(pdf_path)],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        page_count = 1
        if completed.returncode == 0:
            match = re.search(r"^Pages:\s+(\d+)\s*$", completed.stdout, re.MULTILINE)
            if match:
                page_count = max(1, int(match.group(1)))
    except Exception:
        page_count = 1

    pages = _sample_page_image_paths([str(index) for index in range(1, page_count + 1)], max_samples=max_samples)
    rendered: list[str] = []
    for page in pages:
        page_number = int(page)
        prefix = staging_dir / f"sample-page-{page_number}"
        try:
            subprocess.run(
                [
                    "pdftoppm",
                    "-png",
                    "-singlefile",
                    "-f",
                    str(page_number),
                    "-l",
                    str(page_number),
                    str(pdf_path),
                    str(prefix),
                ],
                capture_output=True,
                text=True,
                check=True,
                timeout=60,
            )
        except Exception:
            continue
        image_path = prefix.with_suffix(".png")
        if image_path.exists():
            rendered.append(str(image_path))
    return rendered


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
    subfolder_path: str
    title: str
    filename_slug: str
    summary: str
    key_insights: list[str]
    actions: list[str]
    open_questions: list[str]
    rewritten_markdown: str
    high_level_category: str
    sentiment: str
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
    size_bytes: int,
    extracted_text: str | None,
    extracted_text_reliability: str,
    page_image_paths: list[str],
    timestamp: datetime,
    rewrite_eligible: bool,
) -> str:
    payload = {
        "source_path": path,
        "source_kind": source_kind,
        "original_filename": original_name,
        "original_extension": extension,
        "content_type": content_type or "",
        "size_bytes": size_bytes,
        "source_timestamp_utc": timestamp.astimezone(UTC).isoformat(),
        "extracted_text": (extracted_text or "")[:FILE_AGENT_MAX_TEXT_CHARS],
        "extracted_text_reliability": extracted_text_reliability,
        "page_image_paths": page_image_paths[:3],
        "rewrite_eligible": rewrite_eligible,
    }
    return (
        "Analyze this inbox file for filing only. "
        "You may inspect the file at source_path with read-only MCP tools if available, "
        "but do not write or move files, do not queue items, and do not perform any side effects. "
        "Treat extracted_text as supplemental and potentially unreliable.\n\n"
        "Return exactly one JSON object with these keys:\n"
        "folder, subfolder_path, title, filename_slug, summary, key_insights, actions, open_questions, rewritten_markdown, confidence, reason, high_level_category, sentiment.\n\n"
        "Rules:\n"
        "- folder must be one of Projects, Areas, Resources, Archive, Unfiled.\n"
        "- subfolder_path must be a relative path under the chosen folder, never an absolute path.\n"
        "- when folder is Projects, Areas, Resources, or Archive, subfolder_path should usually contain 1 to 3 stable human-readable segments like Church, School/Assignments/Valerie, Finance/Statements, or FamilyCloud/Docs.\n"
        "- do not repeat the top-level folder name inside subfolder_path.\n"
        "- use an empty string for subfolder_path only when folder is Unfiled or there is truly no confident subfolder.\n"
        "- filename_slug must be short, semantic, and durable. Do not include timestamps or file extensions.\n"
        "- summary must be meaningful prose, not a copied first sentence.\n"
        "- key_insights, actions, and open_questions must be short lists of strings.\n"
        "- high_level_category must be a short top-level label like church, receipt, insurance, project, reference, media, or unknown.\n"
        "- sentiment must be one of positive, neutral, negative, mixed, or unknown.\n"
        "- Use the file itself as the primary object of analysis, not only extracted_text.\n"
        "- If page_image_paths are provided, inspect a representative sample of those page images and use visual cues for classification when readable text is weak or missing.\n"
        "- If extracted_text_reliability is low, do not invent facts from extracted text.\n"
        "- If the note is too ambiguous to classify confidently, use folder Unfiled and explain why.\n"
        "- Do not invent facts not present in the note.\n"
        "- rewritten_markdown may be included only as a suggested rewrite; return an empty string when rewrite_eligible is false or no rewrite is warranted.\n\n"
        f"Input JSON:\n{json.dumps(payload, ensure_ascii=True)}"
    )


def _format_subfolder_segment(value: str) -> str:
    cleaned = _clean_space(value.replace("_", " "))
    cleaned = re.sub(r'[<>:"|?*\x00-\x1f]', "", cleaned)
    cleaned = cleaned.strip(" ./")
    if not cleaned:
        return ""
    words: list[str] = []
    for word in cleaned.split():
        if any(char.isupper() for char in word) or any(char.isdigit() for char in word):
            words.append(word)
            continue
        words.append("-".join(part.capitalize() for part in word.split("-")))
    return " ".join(words)[:60].strip()


def _fallback_subfolder_path(*, folder: str, high_level_category: str) -> str:
    if folder == "Unfiled":
        return ""
    label_source = high_level_category.replace("_", " ").replace("-", " ")
    label = _format_subfolder_segment(label_source)
    if label and label.lower() != "unknown":
        return label
    return DEFAULT_SUBFOLDER_BY_FOLDER.get(folder, "General")


def _normalize_subfolder_path(*, folder: str, subfolder_path: Any, high_level_category: str) -> str:
    if folder == "Unfiled":
        return ""
    raw_value = str(subfolder_path or "").replace("\\", "/")
    segments: list[str] = []
    for raw_segment in raw_value.split("/"):
        segment = _format_subfolder_segment(raw_segment)
        if not segment:
            continue
        if segment.lower() == folder.lower() and not segments:
            continue
        segments.append(segment)
        if len(segments) >= MAX_FILE_AGENT_SUBFOLDER_DEPTH:
            break
    if segments:
        return "/".join(segments)
    return _fallback_subfolder_path(folder=folder, high_level_category=high_level_category)


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
    rewritten_markdown_value = raw.get("rewritten_markdown")
    rewritten_markdown = str(rewritten_markdown_value or "")
    if rewritten_markdown.strip():
        rewritten_markdown = rewritten_markdown if rewritten_markdown.endswith("\n") else rewritten_markdown + "\n"
    else:
        rewritten_markdown = _build_structured_note_markdown(
            title=title,
            summary=summary,
            key_insights=key_insights,
            actions=actions,
            open_questions=open_questions,
            raw_note_content=readable_text,
        )
    high_level_category = _slugify(_clean_space(str(raw.get("high_level_category") or "")) or "unknown").replace("-", "_")
    subfolder_path = _normalize_subfolder_path(
        folder=folder,
        subfolder_path=raw.get("subfolder_path"),
        high_level_category=high_level_category,
    )
    sentiment = _clean_space(str(raw.get("sentiment") or "")).lower() or "unknown"
    if sentiment not in {"positive", "neutral", "negative", "mixed", "unknown"}:
        sentiment = "unknown"
    try:
        confidence = float(raw.get("confidence"))
    except Exception:
        confidence = 0.45
    reason = _clean_space(str(raw.get("reason") or ""))[:280] or "file-agent-generated"
    return FileAgentInboxDecision(
        folder=folder,
        subfolder_path=subfolder_path,
        title=title,
        filename_slug=filename_slug,
        summary=summary,
        key_insights=key_insights,
        actions=actions,
        open_questions=open_questions,
        rewritten_markdown=rewritten_markdown,
        high_level_category=high_level_category,
        sentiment=sentiment,
        confidence=max(0.0, min(confidence, 0.99)),
        reason=reason,
    )


def _extract_json_candidate_text(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    if not stripped:
        return None
    candidates = [stripped]
    start = stripped.find("{")
    end = stripped.rfind("}")
    if 0 <= start < end:
        candidates.append(stripped[start : end + 1])
    for candidate in candidates:
        try:
            decoded = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(decoded, dict):
            return decoded
    return None


def _invoke_file_agent_json(*, prompt: str, timeout_seconds: int) -> dict[str, Any]:
    openclaw_bin = os.environ.get("OPENCLAW_BIN", "openclaw").strip() or "openclaw"
    command = [
        openclaw_bin,
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
        decoded = _extract_json_candidate_text(text)
        if decoded is not None:
            return decoded
    raise RuntimeError("FileAgent returned no JSON payload")


def synthesize_note_with_file_agent(
    *,
    path: str,
    content_type: str | None,
    size_bytes: int,
    extracted_text: str | None,
    extracted_text_reliability: str,
    page_image_paths: list[str],
    timestamp: datetime,
    source_kind: str,
    rewrite_eligible: bool,
) -> FileAgentInboxDecision:
    original_name = _base_name(path)
    _, extension = _split_name(original_name)
    prompt = _file_agent_prompt(
        path=path,
        source_kind=source_kind,
        original_name=original_name,
        extension=extension,
        content_type=content_type,
        size_bytes=size_bytes,
        extracted_text=extracted_text,
        extracted_text_reliability=extracted_text_reliability,
        page_image_paths=page_image_paths,
        timestamp=timestamp,
        rewrite_eligible=rewrite_eligible,
    )
    raw = _invoke_file_agent_json(prompt=prompt, timeout_seconds=FILE_AGENT_TIMEOUT_SECONDS)
    return _parse_file_agent_result(raw, extracted_text or "")


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


def _looks_like_parser_placeholder(text: str | None) -> bool:
    candidate = (text or "").strip()
    if not candidate:
        return False
    return candidate.startswith(PARSER_PLACEHOLDER_PREFIXES)


def _looks_like_image_placeholder_markdown(text: str | None) -> bool:
    candidate = (text or "").strip()
    return candidate.startswith("![](/tmp/pdf-images/") or candidate.startswith("![image](/tmp/pdf-images/")


def _decode_read_payload(payload: dict[str, Any], extension: str) -> tuple[str | None, bytes | None, str, str, list[str], int | None]:
    content_type = str(payload.get("content_type") or "")
    size_value = payload.get("size")
    try:
        observed_size = int(size_value) if size_value is not None else None
    except Exception:
        observed_size = None
    content = payload.get("content")
    if not isinstance(content, str):
        return None, None, content_type, "missing", [], observed_size
    if payload.get("encoding") == "base64":
        raw = base64.b64decode(content)
        extracted = _extract_text_from_bytes(raw, content_type, extension)
        reliability = "high" if extracted else "missing"
        return extracted, raw, content_type, reliability, [], observed_size or len(raw)
    extracted = content.strip() or None
    page_image_paths = _sample_page_image_paths(_extract_page_image_paths(extracted))
    reliability = "low" if (_looks_like_parser_placeholder(extracted) or _looks_like_image_placeholder_markdown(extracted)) else ("high" if extracted else "missing")
    if reliability == "low":
        extracted = None
    return extracted, None, content_type, reliability, page_image_paths, observed_size


async def _extract_readable_text(client: McpNextcloudClient, candidate: InboxCandidate) -> tuple[str | None, str, str, list[str], int | None]:
    _, extension = _split_name(candidate.name)
    content_type = candidate.content_type
    try:
        payload = await client.read_file(candidate.path)
        readable_text, _, parsed_content_type, reliability, page_image_paths, observed_size = _decode_read_payload(payload, extension)
        if parsed_content_type:
            content_type = parsed_content_type
        if readable_text or reliability == "low":
            if extension == ".pdf" and reliability == "low":
                try:
                    raw_payload = await client.read_raw_file(candidate.path)
                    raw_bytes = base64.b64decode(str(raw_payload.get("content") or ""))
                    content_type = str(raw_payload.get("content_type") or content_type)
                    page_image_paths = _pdf_page_samples(raw_bytes, source_path=candidate.path) or page_image_paths
                    observed_size = observed_size or len(raw_bytes)
                except Exception:
                    pass
            return readable_text, content_type, reliability, page_image_paths, observed_size
    except Exception:
        pass
    try:
        raw_payload = await client.read_raw_file(candidate.path)
        raw_bytes = base64.b64decode(str(raw_payload.get("content") or ""))
        content_type = str(raw_payload.get("content_type") or content_type)
        readable_text = _extract_text_from_bytes(raw_bytes, content_type, extension)
        return readable_text, content_type, "high" if readable_text else "missing", [], len(raw_bytes)
    except Exception:
        return None, content_type, "missing", [], None


def _rewrite_eligible(candidate: InboxCandidate) -> bool:
    _, extension = _split_name(candidate.name)
    return extension in NOTE_EXTENSIONS and HOME_DASHBOARD_DOC_RE.match(candidate.name) is not None


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


def _candidate_sort_key(candidate: InboxCandidate) -> tuple[str, str]:
    return (_parse_timestamp(candidate.last_modified).isoformat(), candidate.path)


def _ordered_candidates(candidates: list[InboxCandidate]) -> list[InboxCandidate]:
    return sorted(candidates, key=_candidate_sort_key)


async def discover_candidates(
    client: McpNextcloudClient,
    *,
    ready_tag: str,
    include_dashboard_docs: bool,
    idle_minutes: int,
    candidate_mode: str = "ready-tagged",
) -> tuple[list[InboxCandidate], int, int]:
    try:
        ready_candidates = await client.list_ready_files("/Notes/Inbox", ready_tag)
    except Exception as exc:
        logger.warning("ready_tag_lookup_failed scope=/Notes/Inbox tag=%s error=%s", ready_tag, exc)
        ready_candidates = []
    ready_by_path = {item.path: item for item in ready_candidates}
    skipped_locked = 0
    skipped_recent = 0
    entries = await client.list_directory("/Notes/Inbox")
    entry_by_path: dict[str, InboxCandidate] = {}
    for item in entries:
        entry = _as_file_entry(item)
        if entry is None:
            continue
        entry_by_path[entry.path] = entry
        existing = ready_by_path.get(entry.path)
        if existing is not None and entry.lock_owner:
            existing.lock_owner = entry.lock_owner
        if existing is not None:
            existing.name = entry.name or existing.name
            existing.size = entry.size or existing.size
            existing.content_type = entry.content_type or existing.content_type
            existing.last_modified = entry.last_modified or existing.last_modified
            existing.etag = entry.etag or existing.etag
            existing.file_id = entry.file_id or existing.file_id
    if candidate_mode == "closed-inbox":
        cutoff = datetime.now(UTC) - timedelta(minutes=max(1, idle_minutes)) if idle_minutes > 0 else None
        candidates: list[InboxCandidate] = []
        for entry in entry_by_path.values():
            if entry.lock_owner:
                skipped_locked += 1
                continue
            is_dashboard_doc = HOME_DASHBOARD_DOC_RE.match(entry.name) is not None
            if is_dashboard_doc and not include_dashboard_docs:
                continue
            if entry.size <= 0:
                skipped_recent += 1
                continue
            modified_at = _parse_timestamp(entry.last_modified)
            if cutoff is not None and modified_at > cutoff:
                skipped_recent += 1
                continue
            ready_entry = ready_by_path.get(entry.path)
            if ready_entry is not None:
                ready_entry.lock_owner = entry.lock_owner
                ready_entry.name = entry.name or ready_entry.name
                ready_entry.size = entry.size or ready_entry.size
                ready_entry.content_type = entry.content_type or ready_entry.content_type
                ready_entry.last_modified = entry.last_modified or ready_entry.last_modified
                ready_entry.etag = entry.etag or ready_entry.etag
                ready_entry.file_id = entry.file_id or ready_entry.file_id
                candidates.append(ready_entry)
                continue
            entry.source_kind = "dashboard-doc" if is_dashboard_doc else "closed-inbox"
            candidates.append(entry)
        return candidates, skipped_locked, skipped_recent
    by_path = dict(ready_by_path)
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


def _destination_directory(*, folder: str, high_level_category: str, subfolder_path: str = "") -> str:
    base = f"/Notes/{folder}"
    relative = _normalize_subfolder_path(
        folder=folder,
        subfolder_path=subfolder_path,
        high_level_category=high_level_category,
    )
    if not relative:
        return base
    return f"{base}/{relative}"


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
    high_level_category: str,
    sentiment: str,
) -> bool:
    _, ext = _split_name(destination_path)
    tags = ["ready-processed", folder.lower(), source_kind]
    if high_level_category and high_level_category != "unknown" and high_level_category not in tags:
        tags.append(high_level_category)
    metadata = {
        "source_path": candidate.path,
        "destination_folder": folder,
        "source_file_id": candidate.file_id,
        "file_agent": "shared_inbox_processor",
        "confidence": confidence,
        "filing_reason": reason,
        "source_kind": source_kind,
        "high_level_category": high_level_category,
        "sentiment": sentiment,
    }
    if high_level_category == "church":
        metadata["note_type"] = "church"
    payload_base = {
        "family_id": family_id,
        "actor": actor,
        "source_session_id": "nextcloud-file-agent",
        "path": destination_path,
        "tags": tags,
        "nextcloud_url": nextcloud_url,
        "related_paths": [candidate.path],
        "metadata": metadata,
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
            return True
    except Exception as exc:
        logger.warning(
            "file_inbox_index_failed actor=%s path=%s destination=%s folder=%s error=%s",
            actor,
            candidate.path,
            destination_path,
            folder,
            exc,
        )
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
    question_api_base_url = os.environ.get("QUESTION_API_BASE_URL", decision_api_base_url).rstrip("/")
    try:
        with httpx.Client(timeout=20.0, verify=_verify_for_url(question_api_base_url)) as client:
            payload = {
                "domain": "file",
                "source_agent": "FileAgent",
                "topic": f"Needs filing review: {title}",
                "summary": "Low-confidence inbox filing result needs a human check.",
                "prompt": (
                    f"FileAgent moved `{candidate.path}` to `{destination_path}` with low confidence "
                    f"({confidence:.2f}). Reason: {reason}. Please confirm the final destination."
                ),
                "urgency": "medium",
                "category": "filing_review",
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
            }
            try:
                client.post(
                    f"{decision_api_base_url.rstrip('/')}/families/{family_id}/jobs/followups",
                    headers=_http_headers(actor),
                    json={
                        "actor": actor,
                        "job_type": "create_question",
                        "dedupe_key": f"file-filing-review:{destination_path}",
                        "payload": payload,
                    },
                ).raise_for_status()
                return
            except Exception:
                pass
            client.post(
                f"{question_api_base_url}/families/{family_id}/questions",
                headers=_http_headers(actor),
                json=payload,
            ).raise_for_status()
    except Exception:
        return


def _create_file_open_questions(
    *,
    decision_api_base_url: str,
    actor: str,
    family_id: int,
    destination_path: str,
    title: str,
    open_questions: list[str],
    nextcloud_url: str,
) -> None:
    if not open_questions:
        return
    question_api_base_url = os.environ.get("QUESTION_API_BASE_URL", decision_api_base_url).rstrip("/")
    prompt = " ".join(f"{index + 1}. {item}" for index, item in enumerate(open_questions[:3]))
    try:
        with httpx.Client(timeout=20.0, verify=_verify_for_url(question_api_base_url)) as client:
            payload = {
                "domain": "file",
                "source_agent": "FileAgent",
                "topic": f"Follow-up for filed note: {title}",
                "summary": "FileAgent found unresolved follow-up questions in a filed note.",
                "prompt": prompt,
                "urgency": "medium",
                "category": "file_followup",
                "topic_type": "file_followup",
                "answer_sufficiency_state": "needed",
                "dedupe_key": f"file-followup:{destination_path}",
                "context": {
                    "destination_path": destination_path,
                    "nextcloud_url": nextcloud_url,
                    "open_questions": open_questions[:5],
                },
                "artifact_refs": [{"type": "file", "path": destination_path}],
            }
            try:
                client.post(
                    f"{decision_api_base_url.rstrip('/')}/families/{family_id}/jobs/followups",
                    headers=_http_headers(actor),
                    json={
                        "actor": actor,
                        "job_type": "create_question",
                        "dedupe_key": f"file-followup:{destination_path}",
                        "payload": payload,
                    },
                ).raise_for_status()
                return
            except Exception:
                pass
            client.post(
                f"{question_api_base_url}/families/{family_id}/questions",
                headers=_http_headers(actor),
                json=payload,
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
    candidate_mode: str = "closed-inbox",
    max_candidates: int | None = None,
) -> dict[str, Any]:
    return await _process_candidates_async(
        mcp_url=mcp_url,
        ready_tag=ready_tag,
        decision_api_base_url=decision_api_base_url,
        actor=actor,
        family_id=family_id,
        nextcloud_base_url=nextcloud_base_url,
        include_dashboard_docs=include_dashboard_docs,
        dashboard_idle_minutes=dashboard_idle_minutes,
        confidence_threshold=confidence_threshold,
        candidate_mode=candidate_mode,
        candidates=None,
        max_candidates=max_candidates,
    )


async def _process_candidates_async(
    *,
    mcp_url: str,
    ready_tag: str,
    decision_api_base_url: str,
    actor: str,
    family_id: int,
    nextcloud_base_url: str | None,
    include_dashboard_docs: bool,
    dashboard_idle_minutes: int,
    confidence_threshold: float,
    candidate_mode: str,
    candidates: list[InboxCandidate] | None,
    max_candidates: int | None,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "status": "completed",
        "discovered": 0,
        "deferred": 0,
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
        active_candidates = candidates
        if active_candidates is None:
            active_candidates, skipped_locked, skipped_recent = await discover_candidates(
                client,
                ready_tag=ready_tag,
                include_dashboard_docs=include_dashboard_docs,
                idle_minutes=dashboard_idle_minutes,
                candidate_mode=candidate_mode,
            )
            summary["skipped_locked"] = skipped_locked
            summary["skipped_recent"] = skipped_recent
        active_candidates = _ordered_candidates(active_candidates)
        summary["discovered"] = len(active_candidates)
        effective_max_candidates = max_candidates if isinstance(max_candidates, int) and max_candidates > 0 else None
        if effective_max_candidates is not None and len(active_candidates) > effective_max_candidates:
            summary["deferred"] = len(active_candidates) - effective_max_candidates
            active_candidates = active_candidates[:effective_max_candidates]
        for candidate in active_candidates:
            readable_text, content_type, extracted_text_reliability, page_image_paths, observed_size = await _extract_readable_text(client, candidate)
            timestamp = _parse_timestamp(candidate.last_modified)
            fallback_decision = derive_filing_decision(
                path=candidate.path,
                content_type=content_type,
                readable_text=readable_text,
                timestamp=timestamp,
                source_kind=candidate.source_kind,
            )
            decision = fallback_decision
            rewritten_content: str | None = None
            summary_text: str | None = None
            key_insights: list[str] = []
            open_questions: list[str] = []
            high_level_category = "unknown"
            sentiment = "unknown"
            try:
                ai_decision = synthesize_note_with_file_agent(
                    path=candidate.path,
                    content_type=content_type,
                    size_bytes=observed_size or candidate.size,
                    extracted_text=readable_text,
                    extracted_text_reliability=extracted_text_reliability,
                    page_image_paths=_stage_page_image_paths(page_image_paths, source_path=candidate.path),
                    timestamp=timestamp,
                    source_kind=candidate.source_kind,
                    rewrite_eligible=_rewrite_eligible(candidate),
                )
                filename = f"{timestamp.astimezone(UTC).strftime('%Y-%m-%d_%H%M%S')}_{ai_decision.filename_slug}{_split_name(candidate.name)[1]}"
                decision = {
                    "folder": ai_decision.folder,
                    "subfolder_path": ai_decision.subfolder_path,
                    "filename": filename,
                    "title": ai_decision.title,
                    "readable": bool(readable_text),
                    "descriptive_name": True,
                    "confidence": ai_decision.confidence,
                    "reason": ai_decision.reason,
                }
                if _rewrite_eligible(candidate) and ai_decision.rewritten_markdown:
                    rewritten_content = ai_decision.rewritten_markdown
                summary_text = ai_decision.summary
                key_insights = ai_decision.key_insights
                open_questions = ai_decision.open_questions
                high_level_category = ai_decision.high_level_category
                sentiment = ai_decision.sentiment
            except Exception as exc:
                logger.warning("file_agent_file_synthesis_failed path=%s error=%s", candidate.path, exc)
                fallback_title = _extract_title(readable_text, _split_name(candidate.name)[0] or "captured-file")
                decision = {
                    "folder": "Unfiled",
                    "subfolder_path": "",
                    "filename": f"{timestamp.astimezone(UTC).strftime('%Y-%m-%d_%H%M%S')}_{_slugify(fallback_title)}{_split_name(candidate.name)[1]}",
                    "title": fallback_title,
                    "readable": bool(readable_text),
                    "descriptive_name": bool(fallback_decision.get("descriptive_name")),
                    "confidence": 0.2,
                    "reason": "file-agent-synthesis-failed",
                }
                high_level_category = "unknown"
                sentiment = "unknown"
            folder = str(decision["folder"])
            if float(decision["confidence"]) < confidence_threshold:
                folder = "Unfiled"
            destination_dir = _destination_directory(
                folder=folder,
                high_level_category=high_level_category,
                subfolder_path=str(decision.get("subfolder_path") or ""),
            )
            await _ensure_directory(client, destination_dir)
            destination = await _unique_destination(client, f"{destination_dir}/{decision['filename']}")
            try:
                await client.move_resource(candidate.path, destination)
            except FileExistsError:
                summary["conflicts"].append({"source": candidate.path, "destination": destination})
                continue
            if rewritten_content:
                await client.write_file(destination, rewritten_content, content_type="text/markdown")
            if candidate.source_kind == "ready-tag":
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
                high_level_category=high_level_category,
                sentiment=sentiment,
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
            elif open_questions:
                _create_file_open_questions(
                    decision_api_base_url=decision_api_base_url,
                    actor=actor,
                    family_id=family_id,
                    destination_path=destination,
                    title=str(decision["title"]),
                    open_questions=open_questions,
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


async def replay_unfiled_to_inbox_async(
    *,
    mcp_url: str,
    ready_tag: str = "ready",
    decision_api_base_url: str,
    actor: str,
    family_id: int,
    nextcloud_base_url: str | None = None,
    include_dashboard_docs: bool = False,
    dashboard_idle_minutes: int = 10,
    confidence_threshold: float = 0.7,
    source_path: str = "/Notes/Unfiled",
    target_path: str = "/Notes/Inbox",
    max_candidates: int | None = None,
) -> dict[str, Any]:
    moved: list[dict[str, str]] = []
    replay_candidates: list[InboxCandidate] = []
    async with McpNextcloudClient(mcp_url) as client:
        await _ensure_directory(client, target_path)
        for item in await client.list_directory(source_path):
            entry = _as_file_entry(item)
            if entry is None:
                continue
            if entry.name.startswith(".attachments."):
                continue
            destination = await _unique_destination(client, f"{target_path}/{entry.name}")
            await client.move_resource(entry.path, destination)
            moved.append({"source_path": entry.path, "destination_path": destination})
            replay_candidates.append(
                InboxCandidate(
                    path=destination,
                    name=_base_name(destination),
                    size=entry.size,
                    content_type=entry.content_type,
                    last_modified=entry.last_modified,
                    etag=entry.etag,
                    file_id=entry.file_id,
                    lock_owner=entry.lock_owner,
                    source_kind="replay-unfiled",
                )
            )
    process_summary = await _process_candidates_async(
        mcp_url=mcp_url,
        ready_tag=ready_tag,
        decision_api_base_url=decision_api_base_url,
        actor=actor,
        family_id=family_id,
        nextcloud_base_url=nextcloud_base_url,
        include_dashboard_docs=include_dashboard_docs,
        dashboard_idle_minutes=dashboard_idle_minutes,
        confidence_threshold=confidence_threshold,
        candidate_mode="closed-inbox",
        candidates=replay_candidates,
        max_candidates=max_candidates,
    )
    return {"moved": len(moved), "results": moved, "process_summary": process_summary}
