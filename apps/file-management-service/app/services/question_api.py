from __future__ import annotations

from typing import Any

import httpx

from app.core.config import settings
from app.core.errors import raise_api_error


def create_question(*, family_id: int, actor_email: str | None, payload: dict[str, Any]) -> dict[str, Any]:
    headers: dict[str, str] = {}
    if actor_email:
        headers["X-Dev-User"] = actor_email
    try:
        response = httpx.post(
            f"{settings.question_api_base_url.rstrip('/')}/families/{family_id}/questions",
            json=payload,
            headers=headers,
            timeout=settings.question_api_timeout_seconds,
        )
    except httpx.HTTPError as exc:
        raise_api_error(502, "question_api_unavailable", f"question-service request failed: {exc}")
    if not response.is_success:
        raise_api_error(502, "question_api_error", f"question-service request failed ({response.status_code})")
    body = response.json()
    if not isinstance(body, dict):
        raise_api_error(502, "question_api_invalid_response", "question-service returned invalid JSON")
    return body
