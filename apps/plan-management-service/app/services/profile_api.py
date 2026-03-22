from __future__ import annotations

from typing import Any

import httpx

from app.core.config import settings


def _headers(*, actor_email: str | None = None, internal_admin: bool = False) -> dict[str, str]:
    headers: dict[str, str] = {}
    if actor_email:
        headers["X-Dev-User"] = actor_email
    if internal_admin:
        headers["X-Internal-Admin-Token"] = settings.internal_admin_token
    return headers


def get_profile_detail(
    *,
    family_id: int,
    person_id: str,
    actor_email: str | None,
    internal_admin: bool,
) -> dict[str, Any] | None:
    try:
        response = httpx.get(
            f"{settings.profile_api_base_url.rstrip('/')}/families/{family_id}/profiles/{person_id}",
            headers=_headers(actor_email=actor_email, internal_admin=internal_admin),
            timeout=settings.profile_api_timeout_seconds,
        )
    except httpx.HTTPError:
        return None
    if response.status_code in {403, 404, 502}:
        return None
    if not response.is_success:
        return None
    payload = response.json()
    return payload if isinstance(payload, dict) else None
