from __future__ import annotations

import anyio
from dataclasses import dataclass
import json
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from .settings import task_settings


class TaskMcpError(RuntimeError):
    pass


@dataclass
class TaskMcpClient:
    base_url: str = ""
    timeout_seconds: float = 0.0

    def __post_init__(self) -> None:
        if not self.base_url:
            self.base_url = str(task_settings.task_agent_mcp_url).rstrip("/")
        if not self.timeout_seconds or self.timeout_seconds <= 0:
            self.timeout_seconds = float(task_settings.task_agent_mcp_timeout_seconds or task_settings.http_timeout_seconds)

    def _run(self, fn):
        return anyio.run(fn)

    def discover_tools(self, *, timeout_seconds: float | None = None) -> list[str]:
        timeout = timeout_seconds or self.timeout_seconds

        async def _discover() -> list[str]:
            async with streamablehttp_client(self.base_url, timeout=timeout) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.list_tools()
                    return [tool.name for tool in result.tools]

        return self._run(_discover)

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        async def _call() -> dict[str, Any]:
            async with streamablehttp_client(self.base_url, timeout=self.timeout_seconds) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(name, arguments or {})
                    if getattr(result, "isError", False):
                        raise TaskMcpError(f"MCP tool {name} failed")
                    structured = getattr(result, "structuredContent", None)
                    if isinstance(structured, dict):
                        return structured
                    text_parts: list[str] = []
                    for item in getattr(result, "content", []) or []:
                        text = getattr(item, "text", None)
                        if text:
                            text_parts.append(text)
                    if not text_parts:
                        return {}
                    joined = "\n".join(text_parts)
                    try:
                        parsed = json.loads(joined)
                    except Exception:
                        return {"text": joined}
                    return parsed if isinstance(parsed, dict) else {"data": parsed}

        return self._run(_call)
