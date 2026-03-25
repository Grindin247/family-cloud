from __future__ import annotations

import httpx

from fastapi import HTTPException

from app.core.auth import AuthContext
from app.core.config import settings


def file_api_enabled() -> bool:
    return bool((settings.file_api_base_url or "").strip())


def _is_internal_admin(x_internal_admin_token: str | None) -> bool:
    return bool(x_internal_admin_token and x_internal_admin_token == settings.internal_admin_token)


def _actor(ctx: AuthContext | None, x_dev_user: str | None) -> str:
    if ctx is not None:
        return ctx.email
    if x_dev_user:
        return x_dev_user.strip().lower()
    return ""


def file_proxy_headers(
    *,
    ctx: AuthContext | None,
    x_dev_user: str | None,
    x_internal_admin_token: str | None,
) -> dict[str, str]:
    if _is_internal_admin(x_internal_admin_token) or (settings.auth_mode == "none" and ctx is None and not x_dev_user):
        return {"X-Internal-Admin-Token": settings.internal_admin_token}
    actor = _actor(ctx, x_dev_user)
    if actor:
        return {"X-Dev-User": actor}
    raise HTTPException(status_code=401, detail="missing auth header (X-Forwarded-User)")


def proxy_file_request(
    method: str,
    path: str,
    *,
    headers: dict[str, str],
    params: dict[str, object] | None = None,
    json_body: dict[str, object] | None = None,
):
    if not file_api_enabled():
        raise RuntimeError("file_api_base_url is not configured")
    try:
        response = httpx.request(
            method,
            f"{settings.file_api_base_url.rstrip('/')}{path}",
            headers=headers,
            params=params,
            json=json_body,
            timeout=20.0,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"file-service proxy failed: {exc}") from exc

    if response.status_code == 204:
        return None

    content_type = response.headers.get("content-type", "")
    if content_type.startswith("application/json"):
        payload = response.json()
    else:
        payload = response.text

    if not response.is_success:
        if isinstance(payload, dict) and "detail" in payload:
            raise HTTPException(status_code=response.status_code, detail=payload["detail"])
        raise HTTPException(status_code=response.status_code, detail=str(payload))
    return payload
