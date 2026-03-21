#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import posixpath
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.common.file_inbox import (
    derive_filing_decision as shared_derive_filing_decision,
    infer_file_item_type as shared_infer_file_item_type,
    process_inbox_async as shared_process_inbox_async,
)


CANONICAL_FOLDERS = ("Inbox", "Projects", "Areas", "Resources", "Archive", "Unfiled")
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
WEBDAV_NS = {"d": "DAV:", "oc": "http://owncloud.org/ns"}


def _normalize_path(path: str) -> str:
    clean = posixpath.normpath("/" + (path or "").strip().lstrip("/"))
    return "/" if clean in {"/.", "//"} else clean


def _strip_markdown_title(value: str) -> str:
    line = value.strip().lstrip("#").strip()
    return re.sub(r"\s+", " ", line)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:80].strip("-") or "file"


def _base_name(path: str) -> str:
    return posixpath.basename(path.rstrip("/"))


def _split_name(name: str) -> tuple[str, str]:
    stem, ext = posixpath.splitext(name)
    return stem or name, ext.lower()


def _looks_descriptive(stem: str) -> bool:
    cleaned = re.sub(r"^\d{4}-\d{2}-\d{2}[_-]\d{6}[_-]?", "", stem).strip(" -_")
    if not cleaned:
        return False
    if GENERIC_NAME_RE.match(cleaned):
        return False
    return len(re.findall(r"[a-z0-9]{3,}", cleaned.lower())) >= 2


def _extract_text(raw: bytes, content_type: str | None, extension: str) -> str | None:
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


def _classify_folder(name: str, text: str | None, content_type: str | None) -> str:
    corpus = " ".join(part for part in (name, text or "", content_type or "") if part).lower()
    if any(keyword in corpus for keyword in ARCHIVE_KEYWORDS):
        return "Archive"
    if any(keyword in corpus for keyword in PROJECT_KEYWORDS):
        return "Projects"
    if any(keyword in corpus for keyword in AREA_KEYWORDS):
        return "Areas"
    if any(keyword in corpus for keyword in RESOURCE_KEYWORDS):
        return "Resources"
    return "Resources"


def derive_filing_decision(
    *,
    path: str,
    content_type: str | None,
    readable_text: str | None,
    timestamp: datetime,
) -> dict[str, Any]:
    return shared_derive_filing_decision(
        path=path,
        content_type=content_type,
        readable_text=readable_text,
        timestamp=timestamp,
    )


def infer_file_item_type(content_type: str | None, extension: str, readable_text: str | None) -> str:
    return shared_infer_file_item_type(content_type, extension, readable_text)


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
class ReadyFile:
    path: str
    name: str
    size: int
    content_type: str
    last_modified: str | None
    etag: str | None
    file_id: str | None


@dataclass
class ProcessingResult:
    source_path: str
    destination_path: str
    folder: str
    indexed: bool
    unreadable: bool
    reason: str


class McpNextcloudReader:
    def __init__(self, url: str) -> None:
        self.url = url
        self._transport_cm: Any | None = None
        self._session_cm: Any | None = None
        self.session: Any | None = None

    async def __aenter__(self) -> "McpNextcloudReader":
        try:
            from mcp.client.session import ClientSession
            from mcp.client.streamable_http import streamablehttp_client
        except ModuleNotFoundError as exc:
            raise RuntimeError("Missing MCP client dependency. Activate .venv before running process-ready.") from exc
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

    async def list_ready_files(self, scope: str, tag_name: str) -> list[ReadyFile]:
        assert self.session is not None
        result = await self.session.call_tool(
            "nc_webdav_list_ready_files",
            {"scope": scope, "tag_name": tag_name},
        )
        payload = _tool_payload(result)
        items = payload.get("results") or []
        ready_files: list[ReadyFile] = []
        for item in items:
            if item.get("is_directory"):
                continue
            ready_files.append(
                ReadyFile(
                    path=str(item.get("path") or ""),
                    name=str(item.get("name") or _base_name(str(item.get("path") or ""))),
                    size=int(item.get("size") or 0),
                    content_type=str(item.get("content_type") or ""),
                    last_modified=item.get("last_modified"),
                    etag=item.get("etag"),
                    file_id=str(item.get("file_id") or "") or None,
                )
            )
        return ready_files

    async def read_raw_file(self, path: str) -> tuple[bytes, str]:
        assert self.session is not None
        result = await self.session.call_tool("nc_webdav_read_file_raw", {"path": path})
        payload = _tool_payload(result)
        raw = base64.b64decode(payload["content"])
        return raw, str(payload.get("content_type") or "")


def _tool_payload(result: Any) -> dict[str, Any]:
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        return structured
    content = getattr(result, "content", None)
    if isinstance(content, list):
        for item in content:
            text = getattr(item, "text", None)
            if isinstance(text, str):
                try:
                    decoded = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if isinstance(decoded, dict):
                    return decoded
    raise RuntimeError("MCP tool returned no structured payload")


class NextcloudAutomationClient:
    def __init__(self, *, base_url: str, username: str, password: str, verify: bool = False) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.client = httpx.Client(
            auth=(username, password),
            verify=verify,
            timeout=60.0,
            headers={"OCS-APIRequest": "true"},
            follow_redirects=True,
        )
        self._tag_cache: dict[str, int] = {}

    def close(self) -> None:
        self.client.close()

    def webdav_url(self, path: str) -> str:
        normalized = _normalize_path(path)
        segments = [quote(part, safe="") for part in normalized.strip("/").split("/") if part]
        suffix = "/".join(segments)
        return f"{self.base_url}/remote.php/dav/files/{quote(self.username, safe='')}/{suffix}"

    def ensure_directory(self, path: str) -> None:
        normalized = _normalize_path(path)
        if normalized == "/":
            return
        current = ""
        for segment in normalized.strip("/").split("/"):
            current += "/" + segment
            response = self.client.request("MKCOL", self.webdav_url(current))
            if response.status_code in {201, 405}:
                continue
            if response.status_code == 409:
                raise RuntimeError(f"Parent directory missing while creating {current}")
            response.raise_for_status()

    def move(self, source_path: str, destination_path: str) -> None:
        source = _normalize_path(source_path)
        destination = _normalize_path(destination_path)
        self.ensure_directory(posixpath.dirname(destination) or "/")
        response = self.client.request(
            "MOVE",
            self.webdav_url(source),
            headers={
                "Destination": self.webdav_url(destination),
                "Overwrite": "F",
            },
        )
        if response.status_code in {201, 204}:
            return
        if response.status_code == 412:
            raise FileExistsError(destination)
        response.raise_for_status()

    def unique_destination(self, destination_path: str) -> str:
        normalized = _normalize_path(destination_path)
        parent = posixpath.dirname(normalized)
        stem, ext = _split_name(_base_name(normalized))
        candidate = normalized
        counter = 2
        while self.path_exists(candidate):
            candidate = f"{parent}/{stem}-{counter}{ext}"
            counter += 1
        return candidate

    def path_exists(self, path: str) -> bool:
        response = self.client.request("HEAD", self.webdav_url(path))
        if response.status_code == 404:
            return False
        if response.status_code in {200, 204}:
            return True
        response.raise_for_status()
        return True

    def get_tag_id(self, tag_name: str) -> int:
        cached = self._tag_cache.get(tag_name)
        if cached is not None:
            return cached
        response = self.client.request(
            "PROPFIND",
            f"{self.base_url}/remote.php/dav/systemtags/",
            headers={"Depth": "1", "Content-Type": "application/xml"},
            content=(
                '<?xml version="1.0"?>'
                '<d:propfind xmlns:d="DAV:" xmlns:oc="http://owncloud.org/ns">'
                "<d:prop><oc:id/><oc:display-name/><d:displayname/></d:prop>"
                "</d:propfind>"
            ),
        )
        response.raise_for_status()
        root = ET.fromstring(response.text)
        for node in root.findall("d:response", WEBDAV_NS):
            display = node.findtext(".//oc:display-name", default="", namespaces=WEBDAV_NS)
            if not display:
                display = node.findtext(".//d:displayname", default="", namespaces=WEBDAV_NS)
            if display != tag_name:
                continue
            raw_id = node.findtext(".//oc:id", default="", namespaces=WEBDAV_NS)
            if not raw_id:
                continue
            tag_id = int(raw_id)
            self._tag_cache[tag_name] = tag_id
            return tag_id
        raise RuntimeError(f"Nextcloud tag not found: {tag_name}")

    def remove_tag(self, file_id: str, tag_name: str) -> None:
        if not file_id:
            return
        tag_id = self.get_tag_id(tag_name)
        response = self.client.request(
            "DELETE",
            f"{self.base_url}/remote.php/dav/systemtags-relations/files/{quote(file_id, safe='')}/{tag_id}",
        )
        if response.status_code in {200, 204, 404}:
            return
        response.raise_for_status()

    def delete_directory(self, path: str) -> bool:
        normalized = _normalize_path(path)
        response = self.client.request("DELETE", self.webdav_url(normalized))
        if response.status_code in {200, 204, 404}:
            return response.status_code != 404
        if response.status_code == 409:
            return False
        response.raise_for_status()
        return True

    def list_tags(self, file_id: str) -> list[str]:
        if not file_id:
            return []
        response = self.client.request(
            "PROPFIND",
            f"{self.base_url}/remote.php/dav/systemtags-relations/files/{quote(file_id, safe='')}",
            headers={"Depth": "1", "Content-Type": "application/xml"},
            content=(
                '<?xml version="1.0"?>'
                '<d:propfind xmlns:d="DAV:" xmlns:oc="http://owncloud.org/ns">'
                "<d:prop><oc:display-name/></d:prop>"
                "</d:propfind>"
            ),
        )
        if response.status_code == 404:
            return []
        response.raise_for_status()
        root = ET.fromstring(response.text)
        tags: list[str] = []
        for node in root.findall("d:response", WEBDAV_NS):
            name = node.findtext(".//oc:display-name", default="", namespaces=WEBDAV_NS)
            if name:
                tags.append(name)
        return tags

    def list_ready_files(self, scope: str, tag_name: str) -> list[ReadyFile]:
        ready_files: list[ReadyFile] = []
        for item in self.list_directory(scope):
            if item["is_directory"]:
                continue
            tags = self.list_tags(str(item.get("file_id") or ""))
            if tag_name not in tags:
                continue
            ready_files.append(
                ReadyFile(
                    path=str(item["path"]),
                    name=_base_name(str(item["path"])),
                    size=0,
                    content_type=str(item.get("content_type") or ""),
                    last_modified=item.get("last_modified"),
                    etag=None,
                    file_id=str(item.get("file_id") or "") or None,
                )
            )
        return ready_files

    def read_file(self, path: str) -> tuple[bytes, str]:
        response = self.client.get(self.webdav_url(path))
        response.raise_for_status()
        return response.content, response.headers.get("content-type", "")

    def list_directory(self, path: str) -> list[dict[str, Any]]:
        normalized = _normalize_path(path)
        response = self.client.request(
            "PROPFIND",
            self.webdav_url(normalized),
            headers={"Depth": "1", "Content-Type": "application/xml"},
            content=(
                '<?xml version="1.0"?>'
                '<d:propfind xmlns:d="DAV:" xmlns:oc="http://owncloud.org/ns">'
                "<d:prop><d:getcontenttype/><d:getlastmodified/><d:resourcetype/><oc:fileid/></d:prop>"
                "</d:propfind>"
            ),
        )
        if response.status_code == 404:
            return []
        response.raise_for_status()
        root = ET.fromstring(response.text)
        items: list[dict[str, Any]] = []
        for index, node in enumerate(root.findall("d:response", WEBDAV_NS)):
            href = node.findtext("d:href", default="", namespaces=WEBDAV_NS)
            item_path = self._path_from_href(href)
            if index == 0 or item_path == normalized:
                continue
            item_type = "directory" if node.find(".//d:collection", WEBDAV_NS) is not None else "file"
            items.append(
                {
                    "path": item_path,
                    "is_directory": item_type == "directory",
                    "content_type": node.findtext(".//d:getcontenttype", default="", namespaces=WEBDAV_NS),
                    "last_modified": node.findtext(".//d:getlastmodified", default="", namespaces=WEBDAV_NS),
                    "file_id": node.findtext(".//oc:fileid", default="", namespaces=WEBDAV_NS),
                }
            )
        return items

    def _path_from_href(self, href: str) -> str:
        marker = f"/remote.php/dav/files/{self.username}"
        if marker not in href:
            return "/"
        suffix = href.split(marker, 1)[1]
        return _normalize_path(httpx.URL(suffix).path)


def _resolve_credentials(args: argparse.Namespace) -> tuple[str, str]:
    username = args.username or os.environ.get("NEXTCLOUD_AUTOMATION_USERNAME") or os.environ.get("NEXTCLOUD_USERNAME")
    password = args.password or os.environ.get("NEXTCLOUD_AUTOMATION_PASSWORD") or os.environ.get("NEXTCLOUD_PASSWORD")
    if not username or not password:
        root = Path(__file__).resolve().parents[1]
        username_file = root / "secrets" / "nextcloud_mcp_username"
        password_file = root / "secrets" / "nextcloud_mcp_app_password"
        if not username and username_file.exists():
            username = username_file.read_text(encoding="utf-8").strip()
        if not password and password_file.exists():
            password = password_file.read_text(encoding="utf-8").strip()
    if not username or not password:
        raise RuntimeError("Missing Nextcloud automation credentials")
    return username.strip(), password.strip()


@lru_cache(maxsize=1)
def _load_repo_env() -> dict[str, str]:
    root = Path(__file__).resolve().parents[1]
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
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def _file_timestamp(last_modified: str | None) -> datetime:
    if last_modified:
        try:
            return parsedate_to_datetime(last_modified).astimezone(UTC)
        except Exception:
            pass
    return datetime.now(UTC)


def _default_base_url() -> str:
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


def _build_nextcloud_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/apps/files/files{quote(_normalize_path(path), safe='/')}"


@lru_cache(maxsize=32)
def _resolve_actor_context(decision_api_base_url: str, family_id: int, actor: str) -> dict[str, Any]:
    with httpx.Client(timeout=15.0) as client:
        response = client.get(
            f"{decision_api_base_url.rstrip('/')}/families/{family_id}/context",
            headers={"X-Dev-User": actor},
        )
        response.raise_for_status()
        return response.json()


def index_document(
    *,
    decision_api_base_url: str,
    actor: str,
    family_id: int,
    item: ReadyFile,
    destination_path: str,
    folder: str,
    readable_text: str | None,
    content_type: str,
    title: str,
) -> bool:
    if not actor or not family_id:
        return False
    ext = posixpath.splitext(destination_path)[1].lower()
    owner_person_id: str | None = None
    try:
        owner_person_id = str(_resolve_actor_context(decision_api_base_url, family_id, actor).get("person_id") or "")
    except Exception:
        owner_person_id = None
    payload_base = {
        "family_id": family_id,
        "actor": actor,
        "owner_person_id": owner_person_id or None,
        "source_session_id": "nextcloud-file-agent",
        "path": destination_path,
        "tags": ["ready-processed", folder.lower()],
        "nextcloud_url": _build_nextcloud_url(_default_base_url(), destination_path),
        "related_paths": [item.path],
        "metadata": {
            "source_path": item.path,
            "destination_folder": folder,
            "source_file_id": item.file_id,
            "file_agent": "nextcloud_para_agent",
        },
    }
    try:
        with httpx.Client(timeout=30.0) as client:
            if readable_text and ext in NOTE_EXTENSIONS:
                response = client.post(
                    f"{decision_api_base_url.rstrip('/')}/notes/index",
                    headers={"X-Dev-User": actor},
                    json={
                        **payload_base,
                        "item_type": "polished",
                        "role": infer_note_role(folder),
                        "title": title,
                        "summary": readable_text[:280],
                        "body_text": readable_text[:4000],
                        "excerpt_text": readable_text[:500],
                        "content_type": content_type or "text/plain",
                    },
                )
            else:
                response = client.post(
                    f"{decision_api_base_url.rstrip('/')}/files/index",
                    headers={"X-Dev-User": actor},
                    json={
                        **payload_base,
                        "name": _base_name(destination_path),
                        "item_type": infer_file_item_type(content_type, ext, readable_text),
                        "role": infer_file_role(folder),
                        "title": title,
                        "summary": readable_text[:280] if readable_text else None,
                        "body_text": readable_text[:4000] if readable_text else None,
                        "excerpt_text": readable_text[:500] if readable_text else None,
                        "content_type": content_type or None,
                        "size_bytes": item.size,
                        "etag": item.etag,
                        "file_id": item.file_id,
                    },
                )
            response.raise_for_status()
            return True
    except Exception:
        return False


async def process_ready_files_async(args: argparse.Namespace) -> dict[str, Any]:
    return await shared_process_inbox_async(
        mcp_url=args.mcp_url,
        ready_tag=args.ready_tag,
        decision_api_base_url=args.decision_api_base_url,
        actor=args.actor,
        family_id=args.family_id,
        nextcloud_base_url=args.base_url,
        include_dashboard_docs=True,
        dashboard_idle_minutes=int(os.environ.get("FILE_AGENT_NEW_DOC_IDLE_MINUTES", "10")),
        confidence_threshold=float(os.environ.get("FILE_AGENT_AUTOFILE_CONFIDENCE_THRESHOLD", "0.70")),
    )


def _collect_migration_moves(client: NextcloudAutomationClient, source_root: str) -> tuple[list[tuple[str, str]], list[str], list[str]]:
    moves: list[tuple[str, str]] = []
    conflicts: list[str] = []
    directories: list[str] = []
    stack = [source_root]
    while stack:
        current = stack.pop()
        directories.append(current)
        for item in client.list_directory(current):
            path = item["path"]
            if item["is_directory"]:
                stack.append(path)
                continue
            relative = posixpath.relpath(path, source_root)
            destination = _normalize_path(f"/Notes/{relative}")
            if client.path_exists(destination):
                conflicts.append(destination)
                continue
            moves.append((path, destination))
    return moves, conflicts, directories


def migrate_familycloud(args: argparse.Namespace) -> dict[str, Any]:
    username, password = _resolve_credentials(args)
    client = NextcloudAutomationClient(
        base_url=args.base_url,
        username=username,
        password=password,
        verify=args.verify_tls,
    )
    try:
        for folder in CANONICAL_FOLDERS:
            client.ensure_directory(f"/Notes/{folder}")
        source_root = "/Notes/FamilyCloud"
        moves, conflicts, directories = _collect_migration_moves(client, source_root)
        executed = 0
        for source, destination in moves:
            client.move(source, destination)
            executed += 1
        removed_legacy_root = False
        for directory in sorted(directories, key=lambda value: value.count('/'), reverse=True):
            try:
                client.delete_directory(directory)
            except Exception:
                continue
        removed_legacy_root = not client.path_exists(source_root)
        return {
            "moved": executed,
            "conflicts": conflicts,
            "removed_legacy_root": removed_legacy_root,
        }
    finally:
        client.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="FamilyCloud Nextcloud PARA migration and filing utilities.")
    parser.add_argument("--base-url", default=_default_base_url())
    parser.add_argument("--mcp-url", default=os.environ.get("NEXTCLOUD_MCP_URL", "http://127.0.0.1:8002/mcp"))
    parser.add_argument("--username")
    parser.add_argument("--password")
    parser.add_argument("--verify-tls", action="store_true")
    subparsers = parser.add_subparsers(dest="command", required=True)

    process_parser = subparsers.add_parser("process-ready", help="Process ready-tagged files in /Notes/Inbox.")
    process_parser.add_argument("--ready-tag", default=os.environ.get("NEXTCLOUD_READY_TAG_NAME", "ready"))
    process_parser.add_argument("--family-id", type=int, default=int(os.environ.get("FILE_AGENT_FAMILY_ID", "2")))
    process_parser.add_argument(
        "--actor",
        default=os.environ.get("FILE_AGENT_ACTOR") or os.environ.get("NEXTCLOUD_USERNAME", ""),
    )
    process_parser.add_argument(
        "--decision-api-base-url",
        default=os.environ.get("DECISION_API_BASE_URL")
        or (f"https://decision.{_load_repo_env().get('FAMILY_DOMAIN', '').strip()}/api/v1" if _load_repo_env().get("FAMILY_DOMAIN") else "http://127.0.0.1:8010/v1"),
    )
    process_parser.add_argument("--summary-json", action="store_true")

    migrate_parser = subparsers.add_parser("migrate-familycloud", help="Move /Notes/FamilyCloud contents into /Notes.")
    migrate_parser.add_argument("--summary-json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "process-ready":
        summary = asyncio.run(process_ready_files_async(args))
    else:
        summary = migrate_familycloud(args)
    if args.summary_json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
