from __future__ import annotations

from typing import Any

import httpx

from app.core.config import settings
from app.core.errors import raise_api_error


def _headers(*, actor_email: str | None = None, internal_admin: bool = False) -> dict[str, str]:
    headers: dict[str, str] = {}
    if actor_email:
        headers["X-Dev-User"] = actor_email
    if internal_admin:
        headers["X-Internal-Admin-Token"] = settings.decision_internal_admin_token
    return headers


def _request(
    method: str,
    path: str,
    *,
    actor_email: str | None,
    internal_admin: bool,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
) -> httpx.Response:
    try:
        return httpx.request(
            method=method,
            url=f"{settings.decision_api_base_url.rstrip('/')}{path}",
            headers=_headers(actor_email=actor_email, internal_admin=internal_admin),
            params=params,
            json=json_body,
            timeout=settings.decision_api_timeout_seconds,
        )
    except httpx.HTTPError as exc:
        raise_api_error(502, "decision_api_unavailable", f"decision-system request failed: {exc}")
    raise AssertionError("unreachable")


def ensure_family_access(*, family_id: int, actor_email: str | None, internal_admin: bool) -> None:
    if not internal_admin and not actor_email:
        raise_api_error(401, "missing_auth", "missing auth header (X-Forwarded-User or X-Dev-User)")
    response = _request("GET", f"/families/{family_id}", actor_email=actor_email, internal_admin=internal_admin)
    if response.status_code == 404:
        raise_api_error(404, "family_not_found", "family not found", {"family_id": family_id})
    if response.status_code == 401:
        raise_api_error(401, "missing_auth", "missing auth header (X-Forwarded-User or X-Dev-User)")
    if response.status_code == 403:
        raise_api_error(403, "family_membership_required", "family membership required", {"family_id": family_id})
    if not response.is_success:
        raise_api_error(502, "decision_api_error", f"decision-system access check failed ({response.status_code})")


def ensure_files_enabled(*, family_id: int, actor_email: str | None, internal_admin: bool) -> None:
    response = _request("GET", f"/families/{family_id}/features", actor_email=actor_email, internal_admin=internal_admin)
    if response.status_code == 404:
        raise_api_error(404, "family_not_found", "family not found", {"family_id": family_id})
    if response.status_code == 401:
        raise_api_error(401, "missing_auth", "missing auth header (X-Forwarded-User or X-Dev-User)")
    if response.status_code == 403:
        raise_api_error(403, "family_membership_required", "family membership required", {"family_id": family_id})
    if not response.is_success:
        raise_api_error(502, "decision_api_error", f"decision-system feature check failed ({response.status_code})")
    items = response.json().get("items", [])
    enabled = next((bool(item.get("enabled")) for item in items if item.get("feature_key") == "files"), False)
    if not enabled:
        raise_api_error(404, "files_disabled", "file domain is disabled for this family", {"family_id": family_id})


def get_family_context(*, family_id: int, actor_email: str | None, target_person_id: str | None = None) -> dict[str, Any]:
    if not actor_email:
        raise_api_error(401, "missing_auth", "missing auth header (X-Forwarded-User or X-Dev-User)")
    response = _request(
        "GET",
        f"/families/{family_id}/context",
        actor_email=actor_email,
        internal_admin=False,
        params={"target_person_id": target_person_id} if target_person_id else None,
    )
    if response.status_code == 404:
        raise_api_error(404, "family_not_found", "family not found", {"family_id": family_id})
    if response.status_code == 401:
        raise_api_error(401, "missing_auth", "missing auth header (X-Forwarded-User or X-Dev-User)")
    if response.status_code == 403:
        raise_api_error(403, "family_membership_required", "family membership required", {"family_id": family_id})
    if not response.is_success:
        raise_api_error(502, "decision_api_error", f"decision-system context lookup failed ({response.status_code})")
    payload = response.json()
    if not isinstance(payload, dict):
        raise_api_error(502, "decision_api_invalid_response", "decision-system context lookup returned invalid JSON")
    return payload


def get_family_features(*, family_id: int, actor_email: str | None, internal_admin: bool) -> list[dict[str, Any]]:
    if not internal_admin and not actor_email:
        raise_api_error(401, "missing_auth", "missing auth header (X-Forwarded-User or X-Dev-User)")
    response = _request("GET", f"/families/{family_id}/features", actor_email=actor_email, internal_admin=internal_admin)
    if response.status_code == 404:
        raise_api_error(404, "family_not_found", "family not found", {"family_id": family_id})
    if response.status_code == 401:
        raise_api_error(401, "missing_auth", "missing auth header (X-Forwarded-User or X-Dev-User)")
    if response.status_code == 403:
        raise_api_error(403, "family_membership_required", "family membership required", {"family_id": family_id})
    if not response.is_success:
        raise_api_error(502, "decision_api_error", f"decision-system feature check failed ({response.status_code})")
    payload = response.json()
    items = payload.get("items", []) if isinstance(payload, dict) else None
    if not isinstance(items, list):
        raise_api_error(502, "decision_api_invalid_response", "decision-system feature lookup returned invalid items")
    return [item for item in items if isinstance(item, dict)]


def write_family_memory(
    *,
    family_id: int,
    actor_email: str | None,
    internal_admin: bool,
    type: str,
    text: str,
    owner_person_id: str | None = None,
    visibility_scope: str = "family",
    source_refs: list[dict[str, Any]] | None = None,
) -> None:
    response = _request(
        "POST",
        f"/family/{family_id}/memory/documents",
        actor_email=actor_email,
        internal_admin=internal_admin,
        json_body={
            "family_id": family_id,
            "type": type,
            "text": text,
            "owner_person_id": owner_person_id,
            "visibility_scope": visibility_scope,
            "source_refs": source_refs or [],
        },
    )
    if not response.is_success:
        raise_api_error(502, "decision_api_error", f"decision-system memory write failed ({response.status_code})")
