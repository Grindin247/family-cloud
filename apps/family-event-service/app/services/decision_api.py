from __future__ import annotations

import httpx
from fastapi import HTTPException
from typing import Any

from app.core.config import settings


def _headers(*, actor_email: str | None = None, internal_admin: bool = False) -> dict[str, str]:
    headers: dict[str, str] = {}
    if actor_email:
        headers["X-Dev-User"] = actor_email
    if internal_admin:
        headers["X-Internal-Admin-Token"] = settings.internal_admin_token
    return headers


def _request(
    path: str,
    *,
    actor_email: str | None,
    internal_admin: bool = False,
    params: dict[str, Any] | None = None,
    failure_prefix: str,
) -> httpx.Response:
    try:
        return httpx.get(
            f"{settings.decision_api_base_url.rstrip('/')}{path}",
            headers=_headers(actor_email=actor_email, internal_admin=internal_admin),
            params=params,
            timeout=settings.decision_api_timeout_seconds,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"{failure_prefix}: {exc}") from exc


def ensure_family_access(*, family_id: int, actor_email: str | None, internal_admin: bool) -> None:
    if internal_admin:
        return
    if not actor_email:
        raise HTTPException(status_code=401, detail="missing auth header (X-Forwarded-User or X-Dev-User)")
    response = _request(
        f"/families/{family_id}/members",
        actor_email=actor_email,
        failure_prefix="decision-system access check failed",
    )
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
    response = _request(
        f"/families/{family_id}/features",
        actor_email=actor_email,
        failure_prefix="decision-system feature check failed",
    )
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


def get_me(*, actor_email: str | None) -> dict[str, Any]:
    if not actor_email:
        raise HTTPException(status_code=401, detail="missing auth header (X-Forwarded-User or X-Dev-User)")
    response = _request(
        "/me",
        actor_email=actor_email,
        failure_prefix="decision-system me lookup failed",
    )
    if response.status_code == 401:
        raise HTTPException(status_code=401, detail="missing auth header (X-Forwarded-User or X-Dev-User)")
    if not response.is_success:
        raise HTTPException(status_code=502, detail=f"decision-system me lookup failed ({response.status_code})")
    payload = response.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail="decision-system me lookup returned invalid JSON")
    return payload


def get_family_context(
    *,
    family_id: int,
    actor_email: str | None,
    target_person_id: str | None = None,
) -> dict[str, Any]:
    if not actor_email:
        raise HTTPException(status_code=401, detail="missing auth header (X-Forwarded-User or X-Dev-User)")
    params = {"target_person_id": target_person_id} if target_person_id else None
    response = _request(
        f"/families/{family_id}/context",
        actor_email=actor_email,
        params=params,
        failure_prefix="decision-system context lookup failed",
    )
    if response.status_code == 404:
        raise HTTPException(status_code=404, detail="family not found")
    if response.status_code == 401:
        raise HTTPException(status_code=401, detail="missing auth header (X-Forwarded-User or X-Dev-User)")
    if response.status_code == 403:
        detail = response.json().get("detail") if response.headers.get("content-type", "").startswith("application/json") else None
        raise HTTPException(status_code=403, detail=detail or "family membership required")
    if not response.is_success:
        raise HTTPException(status_code=502, detail=f"decision-system context lookup failed ({response.status_code})")
    payload = response.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail="decision-system context lookup returned invalid JSON")
    return payload


def get_family_persons(*, family_id: int, actor_email: str | None) -> list[dict[str, Any]]:
    if not actor_email:
        raise HTTPException(status_code=401, detail="missing auth header (X-Forwarded-User or X-Dev-User)")
    response = _request(
        f"/families/{family_id}/persons",
        actor_email=actor_email,
        failure_prefix="decision-system persons lookup failed",
    )
    if response.status_code == 404:
        raise HTTPException(status_code=404, detail="family not found")
    if response.status_code == 401:
        raise HTTPException(status_code=401, detail="missing auth header (X-Forwarded-User or X-Dev-User)")
    if response.status_code == 403:
        detail = response.json().get("detail") if response.headers.get("content-type", "").startswith("application/json") else None
        raise HTTPException(status_code=403, detail=detail or "family membership required")
    if not response.is_success:
        raise HTTPException(status_code=502, detail=f"decision-system persons lookup failed ({response.status_code})")
    payload = response.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail="decision-system persons lookup returned invalid JSON")
    items = payload.get("items", [])
    if not isinstance(items, list):
        raise HTTPException(status_code=502, detail="decision-system persons lookup returned invalid items")
    return [item for item in items if isinstance(item, dict)]
