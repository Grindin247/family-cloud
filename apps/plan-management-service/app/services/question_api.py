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


def create_question(
    *,
    family_id: int,
    payload: dict[str, Any],
    actor_email: str | None,
    internal_admin: bool,
) -> dict[str, Any] | None:
    try:
        response = httpx.post(
            f"{settings.question_api_base_url.rstrip('/')}/families/{family_id}/questions",
            headers=_headers(actor_email=actor_email, internal_admin=internal_admin),
            json=payload,
            timeout=settings.question_api_timeout_seconds,
        )
    except httpx.HTTPError:
        return None
    if not response.is_success:
        return None
    body = response.json()
    return body if isinstance(body, dict) else None
