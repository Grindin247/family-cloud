from __future__ import annotations

import argparse
import base64
import logging
import os
import posixpath
from urllib.parse import quote, unquote
import xml.etree.ElementTree as ET
from collections import deque
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import httpx
import uvicorn
from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations
from nextcloud_mcp_server import app as upstream_app
from nextcloud_mcp_server.auth import require_scopes
from nextcloud_mcp_server.config import get_settings
from nextcloud_mcp_server.context import get_client
from nextcloud_mcp_server.observability import get_uvicorn_logging_config
from nextcloud_mcp_server.observability.metrics import instrument_tool


logger = logging.getLogger("family_cloud.nextcloud_mcp_overlay")
_ORIGINAL_CONFIGURE_WEBDAV_TOOLS = upstream_app.configure_webdav_tools
WEBDAV_NS = {"d": "DAV:", "oc": "http://owncloud.org/ns"}


def _normalize_path(path: str) -> str:
    clean = posixpath.normpath("/" + path.strip().lstrip("/"))
    return "/" if clean in {"/.", "//"} else clean


def _is_in_scope(path: str, scope: str) -> bool:
    normalized_path = _normalize_path(path)
    normalized_scope = _normalize_path(scope)
    if normalized_scope == "/":
        return True
    return normalized_path == normalized_scope or normalized_path.startswith(normalized_scope.rstrip("/") + "/")


def _sort_key(item: dict[str, Any]) -> tuple[int, str]:
    raw = item.get("last_modified_timestamp")
    if isinstance(raw, int):
        return (raw, str(item.get("path") or ""))
    raw_modified = item.get("last_modified")
    if isinstance(raw_modified, str) and raw_modified:
        try:
            return (int(parsedate_to_datetime(raw_modified).timestamp()), str(item.get("path") or ""))
        except Exception:
            pass
    return (0, str(item.get("path") or ""))


def _format_ready_file(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": item.get("name") or posixpath.basename(str(item.get("path") or "")),
        "path": item.get("path"),
        "size": item.get("size") or 0,
        "content_type": item.get("content_type") or "",
        "last_modified": item.get("last_modified"),
        "etag": item.get("etag"),
        "file_id": item.get("file_id") or item.get("id"),
        "is_directory": bool(item.get("is_directory", False)),
    }


def _format_file_entry(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": item.get("name") or posixpath.basename(str(item.get("path") or "")),
        "path": item.get("path"),
        "size": item.get("size") or 0,
        "content_type": item.get("content_type") or "",
        "last_modified": item.get("last_modified"),
        "last_modified_timestamp": item.get("last_modified_timestamp"),
        "etag": item.get("etag"),
        "file_id": item.get("file_id") or item.get("id"),
        "is_directory": bool(item.get("is_directory", False)),
        "lock_owner": item.get("lock_owner") or "",
        "lock_owner_display_name": item.get("lock_owner_display_name") or "",
    }


async def _list_directory_entries(client: Any, path: str) -> list[dict[str, Any]]:
    list_directory = getattr(client.webdav, "list_directory", None)
    if list_directory is None:
        raise RuntimeError("Nextcloud MCP upstream does not expose webdav.list_directory")
    result = await list_directory(path)
    if isinstance(result, dict):
        for key in ("files", "items", "results"):
            value = result.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    if isinstance(result, list):
        return [item for item in result if isinstance(item, dict)]
    return []


def _nextcloud_env() -> tuple[str, str, str]:
    host = os.getenv("NEXTCLOUD_HOST", "").rstrip("/")
    username = os.getenv("NEXTCLOUD_USERNAME", "")
    password = os.getenv("NEXTCLOUD_PASSWORD", "")
    if not host or not username or not password:
        raise RuntimeError("NEXTCLOUD_HOST, NEXTCLOUD_USERNAME, and NEXTCLOUD_PASSWORD are required")
    return host, username, password


def _webdav_url(host: str, username: str, path: str) -> str:
    normalized = _normalize_path(path)
    segments = [quote(part, safe="") for part in normalized.strip("/").split("/") if part]
    suffix = "/".join(segments)
    return f"{host}/remote.php/dav/files/{quote(username, safe='')}/{suffix}"


def _decode_href(username: str, href: str) -> str | None:
    marker = f"/remote.php/dav/files/{quote(username, safe='')}"
    index = href.find(marker)
    if index == -1:
        return None
    suffix = href[index + len(marker) :]
    decoded = [unquote(part) for part in suffix.split("/")]
    return "/" + "/".join(part for part in decoded if part) if decoded else "/"


def _list_directory_entries_with_locks(path: str) -> list[dict[str, Any]]:
    host, username, password = _nextcloud_env()
    response = httpx.request(
        "PROPFIND",
        _webdav_url(host, username, path),
        auth=(username, password),
        headers={"Depth": "1", "Content-Type": "application/xml", "OCS-APIRequest": "true"},
        content=(
            '<?xml version="1.0"?>'
            '<d:propfind xmlns:d="DAV:" xmlns:oc="http://owncloud.org/ns">'
            "<d:prop>"
            "<d:getcontentlength/>"
            "<d:getlastmodified/>"
            "<d:getetag/>"
            "<d:resourcetype/>"
            "<d:getcontenttype/>"
            "<oc:fileid/>"
            "<oc:lock-owner/>"
            "<oc:lock-owner-displayname/>"
            "</d:prop>"
            "</d:propfind>"
        ),
        timeout=30.0,
    )
    if response.status_code == 404:
        return []
    response.raise_for_status()
    root = ET.fromstring(response.text)
    normalized_path = _normalize_path(path)
    entries: list[dict[str, Any]] = []
    for index, node in enumerate(root.findall("d:response", WEBDAV_NS)):
        href = node.findtext("d:href", default="", namespaces=WEBDAV_NS)
        item_path = _decode_href(username, href or "")
        if not item_path or index == 0 or _normalize_path(item_path) == normalized_path:
            continue
        is_directory = node.find(".//d:collection", WEBDAV_NS) is not None
        raw_size = node.findtext(".//d:getcontentlength", default="", namespaces=WEBDAV_NS)
        size = int(raw_size) if raw_size.isdigit() else 0
        entries.append(
            {
                "name": posixpath.basename(_normalize_path(item_path).rstrip("/")) or "/",
                "path": _normalize_path(item_path),
                "is_directory": is_directory,
                "size": size,
                "content_type": node.findtext(".//d:getcontenttype", default="", namespaces=WEBDAV_NS),
                "last_modified": node.findtext(".//d:getlastmodified", default="", namespaces=WEBDAV_NS),
                "etag": node.findtext(".//d:getetag", default="", namespaces=WEBDAV_NS),
                "file_id": node.findtext(".//oc:fileid", default="", namespaces=WEBDAV_NS),
                "lock_owner": node.findtext(".//oc:lock-owner", default="", namespaces=WEBDAV_NS),
                "lock_owner_display_name": node.findtext(".//oc:lock-owner-displayname", default="", namespaces=WEBDAV_NS),
            }
        )
    return entries


def _get_tag_id(tag_name: str) -> int:
    host, username, password = _nextcloud_env()
    response = httpx.request(
        "PROPFIND",
        f"{host}/remote.php/dav/systemtags/",
        auth=(username, password),
        headers={"Depth": "1", "Content-Type": "application/xml", "OCS-APIRequest": "true"},
        content=(
            '<?xml version="1.0"?>'
            '<d:propfind xmlns:d="DAV:" xmlns:oc="http://owncloud.org/ns">'
            "<d:prop><oc:id/><oc:display-name/><d:displayname/></d:prop>"
            "</d:propfind>"
        ),
        timeout=30.0,
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
        if raw_id:
            return int(raw_id)
    raise RuntimeError(f"tag not found: {tag_name}")


def _list_file_tags(file_id: str) -> list[str]:
    if not file_id:
        return []
    host, username, password = _nextcloud_env()
    response = httpx.request(
        "PROPFIND",
        f"{host}/remote.php/dav/systemtags-relations/files/{quote(file_id, safe='')}",
        auth=(username, password),
        headers={"Depth": "1", "Content-Type": "application/xml", "OCS-APIRequest": "true"},
        content=(
            '<?xml version="1.0"?>'
            '<d:propfind xmlns:d="DAV:" xmlns:oc="http://owncloud.org/ns">'
            "<d:prop><oc:display-name/><d:displayname/></d:prop>"
            "</d:propfind>"
        ),
        timeout=30.0,
    )
    if response.status_code == 404:
        return []
    response.raise_for_status()
    root = ET.fromstring(response.text)
    tags: list[str] = []
    for node in root.findall("d:response", WEBDAV_NS):
        display = node.findtext(".//oc:display-name", default="", namespaces=WEBDAV_NS)
        if not display:
            display = node.findtext(".//d:displayname", default="", namespaces=WEBDAV_NS)
        if display:
            tags.append(display)
    return tags


def _list_tagged_entries_fallback(scope: str, tag_name: str) -> list[dict[str, Any]]:
    normalized_scope = _normalize_path(scope)
    queue: deque[str] = deque([normalized_scope])
    visited: set[str] = set()
    results: list[dict[str, Any]] = []
    while queue:
        current = queue.popleft()
        if current in visited:
            continue
        visited.add(current)
        for item in _list_directory_entries_with_locks(current):
            item_path = _normalize_path(str(item.get("path") or ""))
            if not item_path or not _is_in_scope(item_path, normalized_scope):
                continue
            if bool(item.get("is_directory", False)):
                queue.append(item_path)
                continue
            tags = _list_file_tags(str(item.get("file_id") or ""))
            if tag_name in tags:
                results.append(item)
    return results


def _matches_content_type(item: dict[str, Any], content_type_prefixes: list[str]) -> bool:
    if not content_type_prefixes:
        return True
    content_type = str(item.get("content_type") or "").lower()
    return any(content_type.startswith(prefix.lower()) for prefix in content_type_prefixes)


def _matches_modified_after(item: dict[str, Any], modified_after: str | None) -> bool:
    if not modified_after:
        return True
    try:
        threshold = datetime.fromisoformat(modified_after.replace("Z", "+00:00"))
    except Exception:
        return True
    raw_modified = item.get("last_modified")
    if not raw_modified:
        return False
    try:
        modified = parsedate_to_datetime(str(raw_modified))
    except Exception:
        return False
    return modified >= threshold


def _register_ready_files_tool(mcp: FastMCP) -> None:
    @mcp.tool(
        title="List Ready Files",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            openWorldHint=True,
        ),
    )
    @require_scopes("files:read")
    @instrument_tool
    async def nc_webdav_list_ready_files(
        ctx: Context,
        scope: str = "",
        tag_name: str = "ready",
        limit: int | None = None,
    ) -> dict[str, Any]:
        """List Nextcloud files carrying a collaborative/system tag within a path scope."""
        client = await get_client(ctx)
        normalized_scope = _normalize_path(scope or "/")
        logger.info("ready_tag_lookup tag_name=%s scope=%s", tag_name, normalized_scope)
        try:
            tag = await client.webdav.get_tag_by_name(tag_name)
            if not tag or tag.get("id") is None:
                logger.info("ready_tag_not_found tag_name=%s scope=%s", tag_name, normalized_scope)
                return {
                    "success": True,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "scope": normalized_scope,
                    "tag_name": tag_name,
                    "results": [],
                    "total_found": 0,
                }
            files = await client.webdav.get_files_by_tag(int(tag["id"]))
            scoped_results = [
                _format_ready_file(item)
                for item in files
                if not bool(item.get("is_directory", False)) and _is_in_scope(str(item.get("path") or ""), normalized_scope)
            ]
        except Exception as exc:
            logger.warning("ready_tag_lookup_fallback tag_name=%s scope=%s error=%s", tag_name, normalized_scope, exc)
            scoped_results = [_format_ready_file(item) for item in _list_tagged_entries_fallback(normalized_scope, tag_name)]
        scoped_results.sort(key=_sort_key, reverse=True)
        if limit is not None and limit >= 0:
            scoped_results = scoped_results[:limit]
        logger.info(
            "ready_tag_results tag_name=%s scope=%s total=%s",
            tag_name,
            normalized_scope,
            len(scoped_results),
        )
        return {
            "success": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "scope": normalized_scope,
            "tag_name": tag_name,
            "results": scoped_results,
            "total_found": len(scoped_results),
        }

    logger.info("registered_custom_tool name=nc_webdav_list_ready_files")


def _register_stat_tool(mcp: FastMCP) -> None:
    @mcp.tool(
        title="Stat File Path",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            openWorldHint=True,
        ),
    )
    @require_scopes("files:read")
    @instrument_tool
    async def nc_webdav_stat_path(ctx: Context, path: str) -> dict[str, Any]:
        """Return metadata for a single file or directory path."""
        client = await get_client(ctx)
        normalized_path = _normalize_path(path)
        parent = posixpath.dirname(normalized_path) or "/"
        basename = posixpath.basename(normalized_path.rstrip("/")) or "/"
        if normalized_path == "/":
            return {"success": True, "path": "/", "entry": {"path": "/", "name": "/", "is_directory": True}}
        entries = await _list_directory_entries(client, parent)
        for item in entries:
            item_path = _normalize_path(str(item.get("path") or ""))
            item_name = str(item.get("name") or posixpath.basename(item_path))
            if item_path == normalized_path or item_name == basename:
                return {"success": True, "path": normalized_path, "entry": _format_file_entry(item)}
        return {"success": False, "path": normalized_path, "entry": None, "error": "path_not_found"}

    logger.info("registered_custom_tool name=nc_webdav_stat_path")


def _register_detailed_directory_tool(mcp: FastMCP) -> None:
    @mcp.tool(
        title="List Directory With Lock Info",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            openWorldHint=True,
        ),
    )
    @require_scopes("files:read")
    @instrument_tool
    async def nc_webdav_list_directory_detailed(ctx: Context, path: str = "") -> dict[str, Any]:
        """List a directory with lock metadata for safe inbox processing."""
        del ctx
        normalized_path = _normalize_path(path or "/")
        files = _list_directory_entries_with_locks(normalized_path)
        return {
            "success": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "path": normalized_path,
            "files": files,
            "total_count": len(files),
            "directories_count": sum(1 for item in files if item.get("is_directory")),
            "files_count": sum(1 for item in files if not item.get("is_directory")),
            "total_size": sum(int(item.get("size") or 0) for item in files if not item.get("is_directory")),
        }

    logger.info("registered_custom_tool name=nc_webdav_list_directory_detailed")


def _register_recursive_listing_tool(mcp: FastMCP) -> None:
    @mcp.tool(
        title="List Files Recursively",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            openWorldHint=True,
        ),
    )
    @require_scopes("files:read")
    @instrument_tool
    async def nc_webdav_list_files_recursive(
        ctx: Context,
        scope: str = "/",
        max_depth: int = 5,
        limit: int = 500,
        include_directories: bool = False,
        content_type_prefixes: list[str] | None = None,
        modified_after: str | None = None,
        exclude_paths: list[str] | None = None,
    ) -> dict[str, Any]:
        """Recursively list files under a path with basic filtering."""
        client = await get_client(ctx)
        normalized_scope = _normalize_path(scope or "/")
        excluded = {_normalize_path(item) for item in (exclude_paths or []) if str(item).strip()}
        prefixes = [item.strip().lower() for item in (content_type_prefixes or []) if item.strip()]
        queue: deque[tuple[str, int]] = deque([(normalized_scope, 0)])
        results: list[dict[str, Any]] = []
        visited: set[str] = set()
        while queue and len(results) < max(1, limit):
            current_path, depth = queue.popleft()
            if current_path in visited:
                continue
            visited.add(current_path)
            if current_path in excluded:
                continue
            entries = await _list_directory_entries(client, current_path)
            for item in entries:
                normalized_item_path = _normalize_path(str(item.get("path") or ""))
                if normalized_item_path in excluded:
                    continue
                is_directory = bool(item.get("is_directory", False))
                if is_directory and depth < max(0, max_depth):
                    queue.append((normalized_item_path, depth + 1))
                if is_directory and not include_directories:
                    continue
                if not _matches_content_type(item, prefixes):
                    continue
                if not _matches_modified_after(item, modified_after):
                    continue
                results.append(_format_file_entry(item))
                if len(results) >= max(1, limit):
                    break
        results.sort(key=_sort_key, reverse=True)
        return {
            "success": True,
            "scope": normalized_scope,
            "results": results,
            "total_found": len(results),
            "max_depth": max_depth,
        }

    logger.info("registered_custom_tool name=nc_webdav_list_files_recursive")


def _register_tag_listing_tool(mcp: FastMCP) -> None:
    @mcp.tool(
        title="List Tagged Files",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            openWorldHint=True,
        ),
    )
    @require_scopes("files:read")
    @instrument_tool
    async def nc_webdav_list_tagged_files(
        ctx: Context,
        tag_name: str,
        scope: str = "/",
        limit: int | None = None,
    ) -> dict[str, Any]:
        """List files carrying a Nextcloud collaborative/system tag."""
        client = await get_client(ctx)
        normalized_scope = _normalize_path(scope or "/")
        try:
            tag = await client.webdav.get_tag_by_name(tag_name)
            if not tag or tag.get("id") is None:
                return {"success": True, "scope": normalized_scope, "tag_name": tag_name, "results": [], "total_found": 0}
            files = await client.webdav.get_files_by_tag(int(tag["id"]))
            results = [
                _format_file_entry(item)
                for item in files
                if _is_in_scope(str(item.get("path") or ""), normalized_scope)
            ]
        except Exception as exc:
            logger.warning("tag_listing_fallback tag_name=%s scope=%s error=%s", tag_name, normalized_scope, exc)
            results = [_format_file_entry(item) for item in _list_tagged_entries_fallback(normalized_scope, tag_name)]
        results.sort(key=_sort_key, reverse=True)
        if limit is not None and limit >= 0:
            results = results[:limit]
        return {
            "success": True,
            "scope": normalized_scope,
            "tag_name": tag_name,
            "results": results,
            "total_found": len(results),
        }

    logger.info("registered_custom_tool name=nc_webdav_list_tagged_files")


def _register_raw_read_tool(mcp: FastMCP) -> None:
    @mcp.tool(
        title="Read Raw File Bytes",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            openWorldHint=True,
        ),
    )
    @require_scopes("files:read")
    @instrument_tool
    async def nc_webdav_read_file_raw(ctx: Context, path: str) -> dict[str, Any]:
        """Read raw file bytes from Nextcloud without document parsing."""
        client = await get_client(ctx)
        content, content_type = await client.webdav.read_file(path)
        return {
            "path": path,
            "content": base64.b64encode(content).decode("ascii"),
            "content_type": content_type,
            "size": len(content),
            "encoding": "base64",
        }

    logger.info("registered_custom_tool name=nc_webdav_read_file_raw")


def _register_safe_delete_tool(mcp: FastMCP) -> None:
    @mcp.tool(
        title="Delete Or Trash File",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            openWorldHint=True,
        ),
    )
    @require_scopes("files:write")
    @instrument_tool
    async def nc_webdav_safe_delete(ctx: Context, path: str, prefer_trash: bool = True) -> dict[str, Any]:
        """Delete a file, preferring a trash operation when upstream supports it."""
        client = await get_client(ctx)
        normalized_path = _normalize_path(path)
        if prefer_trash:
            trash_resource = getattr(client.webdav, "trash_resource", None)
            if trash_resource is not None:
                await trash_resource(normalized_path)
                return {"success": True, "path": normalized_path, "mode": "trash"}
        delete_resource = getattr(client.webdav, "delete_resource", None)
        if delete_resource is None:
            raise RuntimeError("Nextcloud MCP upstream does not expose trash_resource or delete_resource")
        await delete_resource(normalized_path)
        return {"success": True, "path": normalized_path, "mode": "delete"}

    logger.info("registered_custom_tool name=nc_webdav_safe_delete")


def _register_tag_mutation_tool(mcp: FastMCP) -> None:
    @mcp.tool(
        title="Remove File Tag",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            openWorldHint=True,
        ),
    )
    @require_scopes("files:write")
    @instrument_tool
    async def nc_webdav_remove_tag_from_file(ctx: Context, file_id: str, tag_name: str) -> dict[str, Any]:
        """Remove a collaborative/system tag from a file by file ID."""
        del ctx
        if not file_id:
            return {"success": True, "file_id": file_id, "tag_name": tag_name, "status_code": 204}
        host, username, password = _nextcloud_env()
        tag_id = _get_tag_id(tag_name)
        response = httpx.delete(
            f"{host}/remote.php/dav/systemtags-relations/files/{quote(file_id, safe='')}/{tag_id}",
            auth=(username, password),
            headers={"OCS-APIRequest": "true"},
            timeout=30.0,
        )
        if response.status_code not in {200, 204, 404}:
            response.raise_for_status()
        return {
            "success": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "file_id": file_id,
            "tag_name": tag_name,
            "status_code": response.status_code,
        }

    logger.info("registered_custom_tool name=nc_webdav_remove_tag_from_file")


def _configure_webdav_tools_with_ready(mcp: FastMCP) -> None:
    _ORIGINAL_CONFIGURE_WEBDAV_TOOLS(mcp)
    _register_ready_files_tool(mcp)
    _register_stat_tool(mcp)
    _register_detailed_directory_tool(mcp)
    _register_recursive_listing_tool(mcp)
    _register_tag_listing_tool(mcp)
    _register_raw_read_tool(mcp)
    _register_safe_delete_tool(mcp)
    _register_tag_mutation_tool(mcp)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Nextcloud MCP server with Family Cloud overlay tools.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--log-level", default="info")
    parser.add_argument("--transport", choices=("streamable-http", "http"), default="streamable-http")
    parser.add_argument("--enable-app", action="append", default=[])
    return parser.parse_args()


def _validate_upstream_contract() -> None:
    missing: list[str] = []
    for attr in ("configure_webdav_tools", "get_app"):
        if not hasattr(upstream_app, attr):
            missing.append(f"nextcloud_mcp_server.app.{attr}")
    if missing:
        raise RuntimeError(f"Unsupported upstream nextcloud-mcp-server image; missing: {', '.join(missing)}")


def main() -> None:
    args = _parse_args()
    _validate_upstream_contract()

    upstream_app.configure_webdav_tools = _configure_webdav_tools_with_ready
    app = upstream_app.get_app(
        transport=args.transport,
        enabled_apps=args.enable_app or None,
    )

    settings = get_settings()
    uvicorn_log_config = get_uvicorn_logging_config(
        log_format=settings.log_format,
        log_level=settings.log_level,
        include_trace_context=settings.log_include_trace_context,
    )
    logger.info(
        "starting_nextcloud_mcp_overlay base_image=%s transport=%s enabled_apps=%s ready_tag=%s",
        os.getenv("NEXTCLOUD_MCP_BASE_IMAGE", ""),
        args.transport,
        args.enable_app or ["all"],
        os.getenv("NEXTCLOUD_READY_TAG_NAME", "ready"),
    )
    uvicorn.run(
        app=app,
        host=args.host,
        port=args.port,
        log_level=args.log_level,
        log_config=uvicorn_log_config,
    )


if __name__ == "__main__":
    main()
