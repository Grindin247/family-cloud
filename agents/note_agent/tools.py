from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import base64
import email.utils
import posixpath
import re
from typing import Any

from .mcp_client import NextcloudMcpClient
from .schemas import HealthStatus, ToolInfo
from .settings import note_settings


def _normalize_path(path: str) -> str:
    clean = posixpath.normpath("/" + path.strip().lstrip("/"))
    return clean if clean != "/." else "/"


def _slug(value: str) -> str:
    base = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return base[:80] or "note"


@dataclass
class NextcloudNotesTool:
    client: NextcloudMcpClient = field(default_factory=NextcloudMcpClient)
    discovered_tools: list[ToolInfo] = field(default_factory=list)

    def discover_tools(self) -> list[ToolInfo]:
        self.discovered_tools = self.client.discover_tools()
        return self.discovered_tools

    def healthcheck(self) -> HealthStatus:
        try:
            tools = self.client.discover_tools(timeout_seconds=3.0)
            self.discovered_tools = tools
            return HealthStatus(ok=True, mcp_reachable=True, tools_discovered=[tool.name for tool in tools])
        except Exception as exc:
            return HealthStatus(ok=False, mcp_reachable=False, error=str(exc), tools_discovered=[])

    def ensure_directory(self, path: str) -> str:
        normalized = _normalize_path(path)
        current = ""
        for part in [item for item in normalized.split("/") if item]:
            current = f"{current}/{part}"
            self.client.call_tool("nc_webdav_create_directory", {"path": current})
        return normalized

    def list_directory(self, path: str) -> dict[str, Any]:
        return self.client.call_tool("nc_webdav_list_directory", {"path": _normalize_path(path)})

    def read(self, path: str) -> dict[str, Any]:
        return self.client.call_tool("nc_webdav_read_file", {"path": _normalize_path(path)})

    def read_raw(self, path: str) -> dict[str, Any]:
        return self.client.call_tool("nc_webdav_read_file_raw", {"path": _normalize_path(path)})

    def move(self, path: str, destination_path: str) -> dict[str, Any]:
        return self.client.call_tool(
            "nc_webdav_move_resource",
            {"source_path": _normalize_path(path), "destination_path": _normalize_path(destination_path), "overwrite": False},
        )

    def rename(self, path: str, new_name: str) -> dict[str, Any]:
        parent = posixpath.dirname(_normalize_path(path))
        destination = _normalize_path(posixpath.join(parent, new_name))
        return self.move(path, destination)

    def list_new_in_drop_folder(self, cursor: str | None = None) -> dict[str, Any]:
        listing = self.list_directory(note_settings.note_agent_drop_folder)
        files = listing.get("files", [])
        last_cursor = cursor
        cursor_dt = email.utils.parsedate_to_datetime(cursor) if cursor else None
        new_items: list[dict[str, Any]] = []
        for item in files:
            modified = item.get("last_modified")
            modified_dt = email.utils.parsedate_to_datetime(modified) if modified else None
            if cursor_dt and modified_dt and modified_dt <= cursor_dt:
                continue
            new_items.append(item)
            if modified_dt and (last_cursor is None or modified_dt > email.utils.parsedate_to_datetime(last_cursor)):
                last_cursor = modified
        return {"cursor": last_cursor, "items": new_items}

    def list_inbox_files(self) -> list[dict[str, Any]]:
        listing = self.list_directory(f"{note_settings.note_agent_root}/Inbox")
        files = listing.get("files", [])
        return [item for item in files if not item.get("is_directory")]

    def list_ready_inbox_files(self, scope: str | None = None, tag_name: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
        payload = self.client.call_tool(
            "nc_webdav_list_ready_files",
            {
                "scope": _normalize_path(scope or f"{note_settings.note_agent_root}/Inbox"),
                "tag_name": (tag_name or note_settings.note_agent_ready_tag_name).strip() or note_settings.note_agent_ready_tag_name,
                "limit": limit,
            },
        )
        results = payload.get("results", [])
        return [item for item in results if isinstance(item, dict) and not item.get("is_directory")]

    def upload_media(self, raw_bytes: bytes, filename: str, destination: str | None = None, content_type: str | None = None) -> dict[str, Any]:
        target_dir = self.ensure_directory(destination or f"{note_settings.note_agent_root}/Inbox/Attachments")
        target_path = _normalize_path(posixpath.join(target_dir, filename))
        encoded = base64.b64encode(raw_bytes).decode("ascii")
        mime = f"{content_type or 'application/octet-stream'};base64"
        result = self.client.call_tool("nc_webdav_write_file", {"path": target_path, "content": encoded, "content_type": mime})
        return {"path": target_path, "result": result}

    def write_markdown_note(self, path: str, content: str) -> dict[str, Any]:
        note_path = _normalize_path(path)
        result = self.client.call_tool("nc_webdav_write_file", {"path": note_path, "content": content, "content_type": "text/markdown"})
        return {"path": note_path, "result": result}

    def path_exists(self, path: str) -> bool:
        try:
            self.read(path)
            return True
        except Exception:
            return False

    def ensure_unique_path(self, path: str) -> str:
        normalized = _normalize_path(path)
        if not self.path_exists(normalized):
            return normalized
        parent = posixpath.dirname(normalized)
        name = posixpath.basename(normalized)
        stem, ext = posixpath.splitext(name)
        index = 2
        while True:
            candidate = _normalize_path(posixpath.join(parent, f"{stem}-{index}{ext}"))
            if not self.path_exists(candidate):
                return candidate
            index += 1

    def create_note_in_inbox(
        self,
        *,
        title: str | None,
        content: str,
        template: str | None = None,
        session_id: str | None = None,
        destination: str = "Inbox",
    ) -> dict[str, Any]:
        final_title = (title or "Captured note").strip()
        filed_destination = destination
        category_dir = self.ensure_directory(f"{note_settings.note_agent_root}/{filed_destination}")
        session_prefix = f"{_slug(session_id)}-" if session_id else ""
        filename = f"{session_prefix}{_slug(final_title)}.md"
        note_path = _normalize_path(posixpath.join(category_dir, filename))
        body = template or content
        existing = ""
        try:
            current = self.read(note_path)
            existing = str(current.get("content") or current.get("text") or "")
        except Exception:
            existing = ""
        if existing.strip():
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
            body = existing.rstrip() + f"\n\n## Agent Addendum ({timestamp})\n\n" + content.strip()
        result = self.client.call_tool("nc_webdav_write_file", {"path": note_path, "content": body, "content_type": "text/markdown"})
        return {"path": note_path, "result": result, "appended": bool(existing.strip())}


def note_tools() -> NextcloudNotesTool:
    return NextcloudNotesTool()
