from __future__ import annotations

import argparse
import base64
import logging
import os
import posixpath
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

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
        scoped_results.sort(key=_sort_key, reverse=True)
        if limit is not None and limit >= 0:
            scoped_results = scoped_results[:limit]
        logger.info(
            "ready_tag_results tag_name=%s scope=%s tag_id=%s total=%s",
            tag_name,
            normalized_scope,
            tag["id"],
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


def _configure_webdav_tools_with_ready(mcp: FastMCP) -> None:
    _ORIGINAL_CONFIGURE_WEBDAV_TOOLS(mcp)
    _register_ready_files_tool(mcp)
    _register_raw_read_tool(mcp)


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
