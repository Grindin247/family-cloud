from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx

from agents.common.settings import settings


class ToolClientError(RuntimeError):
    pass


class ToolClientTimeout(ToolClientError):
    pass


class ToolInvocationError(ToolClientError):
    pass


@dataclass(frozen=True)
class ToolCallResult:
    ok: bool
    result: dict[str, Any] | None = None
    error: str | None = None
    attempts: int = 1
    duration_ms: int = 0


class HttpToolClient:
    """
    Pragmatic fallback transport.

    This is NOT MCP transport, but it provides the same "tool adapter" interface
    so agents can run before MCP client transport is wired up.
    """

    def __init__(self, base_url: str | None = None, timeout_seconds: float | None = None, max_retries: int | None = None) -> None:
        self._base_url = (base_url or settings.decision_api_base_url).rstrip("/")
        self._timeout = timeout_seconds or settings.http_timeout_seconds
        self._max_retries = max_retries or settings.http_max_retries

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> ToolCallResult:
        start = time.time()
        attempts = 0
        last_exc: Exception | None = None
        url = f"{self._base_url}{path}"
        for attempts in range(1, self._max_retries + 1):
            try:
                resp = httpx.request(method, url, params=params, json=json_body, headers=headers, timeout=self._timeout)
                if resp.status_code == 204:
                    return ToolCallResult(ok=True, result=None, attempts=attempts, duration_ms=int((time.time() - start) * 1000))
                resp.raise_for_status()
                return ToolCallResult(ok=True, result=resp.json(), attempts=attempts, duration_ms=int((time.time() - start) * 1000))
            except httpx.TimeoutException as exc:
                last_exc = exc
            except Exception as exc:
                last_exc = exc
                break
        duration_ms = int((time.time() - start) * 1000)
        if isinstance(last_exc, httpx.TimeoutException):
            raise ToolClientTimeout(f"timeout calling {method} {url} after {attempts} attempt(s)") from last_exc
        raise ToolInvocationError(f"error calling {method} {url}: {last_exc}") from last_exc

