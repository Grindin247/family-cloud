from __future__ import annotations

from fastapi import HTTPException
import httpx

from app.core.config import settings


def _headers(*, actor_email: str | None = None, internal_admin: bool = False) -> dict[str, str]:
    headers: dict[str, str] = {}
    if actor_email:
        headers["X-Dev-User"] = actor_email
    if internal_admin:
        headers["X-Internal-Admin-Token"] = settings.internal_admin_token
    return headers


def ensure_family_access(*, family_id: int, actor_email: str | None, internal_admin: bool) -> None:
    if internal_admin:
        return
    if not actor_email:
        raise HTTPException(status_code=401, detail="missing auth header (X-Forwarded-User or X-Dev-User)")
    try:
        response = httpx.get(
            f"{settings.decision_api_base_url.rstrip('/')}/families/{family_id}/members",
            headers=_headers(actor_email=actor_email),
            timeout=settings.decision_api_timeout_seconds,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"decision-system access check failed: {exc}") from exc
    if response.status_code == 404:
        raise HTTPException(status_code=404, detail="family not found")
    if response.status_code == 401:
        raise HTTPException(status_code=401, detail="missing auth header (X-Forwarded-User or X-Dev-User)")
    if response.status_code == 403:
        raise HTTPException(status_code=403, detail="family membership required")
    if not response.is_success:
        raise HTTPException(status_code=502, detail=f"decision-system access check failed ({response.status_code})")


def ensure_family_events_enabled(*, family_id: int, actor_email: str | None, internal_admin: bool) -> None:
    if internal_admin:
        return
    if not actor_email:
        raise HTTPException(status_code=401, detail="missing auth header (X-Forwarded-User or X-Dev-User)")
    try:
        response = httpx.get(
            f"{settings.decision_api_base_url.rstrip('/')}/families/{family_id}/features",
            headers=_headers(actor_email=actor_email),
            timeout=settings.decision_api_timeout_seconds,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"decision-system feature check failed: {exc}") from exc
    if response.status_code == 404:
        raise HTTPException(status_code=404, detail="family not found")
    if response.status_code == 401:
        raise HTTPException(status_code=401, detail="missing auth header (X-Forwarded-User or X-Dev-User)")
    if response.status_code == 403:
        raise HTTPException(status_code=403, detail="family membership required")
    if not response.is_success:
        raise HTTPException(status_code=502, detail=f"decision-system feature check failed ({response.status_code})")
    items = response.json().get("items", [])
    enabled = next((bool(item.get("enabled")) for item in items if item.get("feature_key") == "events"), True)
    if not enabled:
        raise HTTPException(status_code=404, detail="events domain is disabled for this family")
