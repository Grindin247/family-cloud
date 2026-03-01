from __future__ import annotations

import anyio
from dataclasses import dataclass
import json
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from .schemas import ToolInfo
from .settings import note_settings


class NoteMcpError(RuntimeError):
    pass


@dataclass
class NextcloudMcpClient:
    base_url: str = note_settings.nextcloud_mcp_url

    def _run(self, func):
        return anyio.run(func)

    def discover_tools(self, *, timeout_seconds: float | None = None) -> list[ToolInfo]:
        timeout = timeout_seconds or note_settings.http_timeout_seconds

        async def _discover() -> list[ToolInfo]:
            async with streamablehttp_client(self.base_url, timeout=timeout) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.list_tools()
                    return [
                        ToolInfo(name=tool.name, description=tool.description or "", input_schema=tool.inputSchema or {})
                        for tool in result.tools
                    ]

        return self._run(_discover)

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        async def _call() -> dict[str, Any]:
            async with streamablehttp_client(self.base_url, timeout=note_settings.http_timeout_seconds) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(name, arguments or {})
                    if getattr(result, "isError", False):
                        raise NoteMcpError(f"MCP tool {name} returned error")
                    structured = getattr(result, "structuredContent", None)
                    if isinstance(structured, dict):
                        return structured
                    text_parts = []
                    for item in getattr(result, "content", []) or []:
                        text = getattr(item, "text", None)
                        if text:
                            text_parts.append(text)
                    if text_parts:
                        joined = "\n".join(text_parts)
                        try:
                            parsed = json.loads(joined)
                        except Exception:
                            return {"text": joined}
                        return parsed if isinstance(parsed, dict) else {"data": parsed}
                    return {}

        return self._run(_call)
