from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.common.family_events import build_event, make_privacy
from app.core.config import settings
from app.models.family_events import FamilyEventRecord


WEBHOOK_EVENTS = [
    "task.created",
    "task.updated",
    "task.deleted",
    "task.assignee.created",
    "task.assignee.deleted",
]


def verify_signature(*, raw_body: bytes, signature: str | None) -> bool:
    secret = settings.task_vikunja_webhook_secret.strip()
    if not secret:
        return True
    if not signature:
        return False
    candidate = signature.strip().lower()
    if candidate.startswith("sha256="):
        candidate = candidate.split("=", 1)[1]
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, candidate)


def get_vikunja_event_name(*, headers: dict[str, str], payload: dict[str, Any]) -> str | None:
    for key in ("x-vikunja-event", "X-Vikunja-Event"):
        value = headers.get(key)
        if value:
            return str(value).strip()
    for key in ("event_name", "event", "type"):
        value = payload.get(key)
        if value:
            return str(value).strip()
    return None


def extract_task_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    queue: list[tuple[dict[str, Any], str]] = []
    for label, candidate in (("task", payload.get("task")), ("data", payload.get("data")), ("entity", payload.get("entity")), ("payload", payload)):
        if isinstance(candidate, dict):
            queue.append((candidate, label))
    seen: set[int] = set()
    best: tuple[int, int, dict[str, Any]] | None = None
    while queue:
        candidate, path = queue.pop(0)
        marker = id(candidate)
        if marker in seen:
            continue
        seen.add(marker)
        if candidate.get("id") is not None and candidate.get("title") is not None:
            score = _task_candidate_score(candidate, path)
            current = (score, len(candidate), candidate)
            if best is None or current > best:
                best = current
        for key, value in candidate.items():
            if isinstance(value, dict):
                queue.append((value, f"{path}.{key}"))
    return best[2] if best is not None and best[0] > 0 else None


def _task_candidate_score(candidate: dict[str, Any], path: str) -> int:
    score = 0
    path_lower = path.lower()
    if path_lower.endswith("task") or ".task." in f"{path_lower}.":
        score += 100
    for key in ("done", "project_id", "updated", "created", "due_date", "done_at", "bucket_id", "description", "identifier", "priority", "percent_done", "start_date", "end_date"):
        if key in candidate:
            score += 10
    for key in ("assignees", "labels", "created_by", "related_tasks", "attachments", "position"):
        if key in candidate:
            score += 4
    if "hex_color" in candidate and "project_id" not in candidate:
        score -= 10
    return score


def extract_actor_id(payload: dict[str, Any]) -> str:
    queue: list[dict[str, Any]] = [payload]
    seen: set[int] = set()
    while queue:
        candidate = queue.pop(0)
        marker = id(candidate)
        if marker in seen:
            continue
        seen.add(marker)
        for key in ("doer", "user", "actor", "updated_by", "created_by"):
            value = candidate.get(key)
            if not isinstance(value, dict):
                continue
            for field in ("email", "username", "name", "id"):
                raw = value.get(field)
                if raw is not None and str(raw).strip():
                    return str(raw).strip().lower()
        for value in candidate.values():
            if isinstance(value, dict):
                queue.append(value)
    return "vikunja-system"


def canonical_task_event_type(*, vikunja_event_name: str, task: dict[str, Any]) -> str | None:
    event_name = str(vikunja_event_name).strip().lower()
    if event_name == "task.created":
        return "task.created"
    if event_name == "task.deleted":
        return "task.deleted"
    if event_name in {"task.assignee.created", "task.assignee.deleted"}:
        return "task.assigned"
    if event_name == "task.updated":
        return "task.completed" if bool(task.get("done")) else "task.updated"
    return None


def deterministic_event_id(*, event_type: str, task_id: int | str, occurred_at: datetime, source_key: str) -> str:
    token = f"{source_key}:{event_type}:{task_id}:{occurred_at.astimezone(UTC).isoformat()}"
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:64]


def build_vikunja_task_event(
    *,
    family_id: int,
    vikunja_event_name: str,
    payload: dict[str, Any],
    task: dict[str, Any] | None = None,
    recorded_at: datetime | None = None,
    source_key: str = "vikunja-webhook",
) -> dict[str, Any] | None:
    task_payload = task or extract_task_payload(payload)
    if task_payload is None:
        return None
    canonical_type = canonical_task_event_type(vikunja_event_name=vikunja_event_name, task=task_payload)
    if canonical_type is None:
        return None
    task_id = task_payload.get("id")
    if task_id is None:
        return None
    occurred_at = _task_occurred_at(task_payload, canonical_type=canonical_type)
    project_id = task_payload.get("project_id")
    project = task_payload.get("project")
    if project_id is None and isinstance(project, dict):
        project_id = project.get("id")
    project_title = project.get("title") if isinstance(project, dict) else None
    actor_id = extract_actor_id(payload)
    title = str(task_payload.get("title") or f"Task {task_id}").strip()
    tags = ["vikunja", "direct"]
    if bool(task_payload.get("done")):
        tags.append("done")
    canonical_payload = {
        "task_id": int(task_id) if str(task_id).isdigit() else task_id,
        "title": title,
        "done": bool(task_payload.get("done")),
        "due_date": task_payload.get("due_date"),
        "project_id": project_id,
        "project_name": project_title,
        "vikunja_event_type": vikunja_event_name,
        "vikunja_updated_at": task_payload.get("updated"),
        "vikunja_created_at": task_payload.get("created"),
    }
    if canonical_type == "task.completed":
        canonical_payload["completed_by"] = actor_id
    event_id = deterministic_event_id(
        event_type=canonical_type,
        task_id=task_id,
        occurred_at=occurred_at,
        source_key=source_key,
    )
    return build_event(
        event_id=event_id,
        family_id=family_id,
        domain="task",
        event_type=canonical_type,
        actor={"actor_type": "user", "actor_id": actor_id},
        subject={"subject_type": "task", "subject_id": str(task_id)},
        payload=canonical_payload,
        source={"agent_id": "Vikunja", "runtime": "backend"},
        privacy=make_privacy(contains_free_text=False),
        tags=tags,
        occurred_at=occurred_at,
        recorded_at=recorded_at,
        integrity={"producer": "Vikunja", "idempotency_key": event_id},
    )


def ensure_project_webhooks() -> dict[str, Any]:
    family_id = int(settings.task_vikunja_family_id)
    target_url = settings.task_vikunja_webhook_target_url.strip()
    if not target_url:
        return {"status": "skipped", "reason": "missing TASK_VIKUNJA_WEBHOOK_TARGET_URL"}
    projects = list_projects()
    created = 0
    unchanged = 0
    replaced = 0
    for project in projects:
        project_id = _int_or_none(project.get("id"))
        if project_id is None:
            continue
        hooks = list_project_webhooks(project_id)
        matching = [hook for hook in hooks if str(hook.get("target_url") or "") == target_url]
        exact = [hook for hook in matching if set(hook.get("events") or []) == set(WEBHOOK_EVENTS)]
        if len(matching) == 1 and len(exact) == 1:
            unchanged += 1
            continue
        for hook in matching:
            if hook.get("id") is None:
                continue
            delete_project_webhook(project_id, int(hook["id"]))
            replaced += 1
        create_project_webhook(
            project_id=project_id,
            target_url=target_url,
            secret=settings.task_vikunja_webhook_secret.strip(),
            events=WEBHOOK_EVENTS,
        )
        created += 1
    return {
        "status": "ok",
        "family_id": family_id,
        "project_count": len(projects),
        "created": created,
        "replaced": replaced,
        "unchanged": unchanged,
        "target_url": target_url,
    }


def reconcile_recent_task_events(db: Session) -> dict[str, Any]:
    family_id = int(settings.task_vikunja_family_id)
    lookback = timedelta(minutes=max(int(settings.task_vikunja_reconcile_lookback_minutes), 1))
    since = datetime.now(UTC) - lookback
    events: list[dict[str, Any]] = []
    scanned = 0
    for project in list_projects():
        project_id = _int_or_none(project.get("id"))
        if project_id is None:
            continue
        for task in list_tasks(project_id):
            scanned += 1
            created_at = _parse_dt(task.get("created"))
            updated_at = _parse_dt(task.get("updated"))
            if created_at and created_at >= since:
                event = build_vikunja_task_event(
                    family_id=family_id,
                    vikunja_event_name="task.created",
                    payload={"task": task},
                    task=task,
                    source_key="vikunja-sweep-created",
                )
                if event is not None and not _event_exists(db, event["event_id"]):
                    events.append(event)
            if updated_at and updated_at >= since:
                event = build_vikunja_task_event(
                    family_id=family_id,
                    vikunja_event_name="task.updated",
                    payload={"task": task},
                    task=task,
                    source_key="vikunja-sweep-updated",
                )
                if event is not None and not _event_exists(db, event["event_id"]):
                    events.append(event)
    deduped: dict[str, dict[str, Any]] = {event["event_id"]: event for event in events}
    return {
        "status": "ok",
        "family_id": family_id,
        "scanned_tasks": scanned,
        "events": list(deduped.values()),
        "ingested": 0,
    }


def list_projects() -> list[dict[str, Any]]:
    payload = _request("GET", "/projects")
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("projects", "items", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def list_tasks(project_id: int) -> list[dict[str, Any]]:
    payload = _request("GET", f"/projects/{project_id}/tasks")
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("tasks", "items", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def list_project_webhooks(project_id: int) -> list[dict[str, Any]]:
    payload = _request("GET", f"/projects/{project_id}/webhooks")
    return payload if isinstance(payload, list) else []


def create_project_webhook(*, project_id: int, target_url: str, secret: str, events: list[str]) -> dict[str, Any]:
    return _request("PUT", f"/projects/{project_id}/webhooks", body={"target_url": target_url, "secret": secret, "events": events})


def delete_project_webhook(project_id: int, webhook_id: int) -> dict[str, Any]:
    return _request("DELETE", f"/projects/{project_id}/webhooks/{webhook_id}")


def _request(method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    headers = {"Accept": "application/json"}
    token = _resolve_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with httpx.Client(base_url=settings.task_vikunja_url.rstrip("/"), timeout=20.0) as client:
        response = client.request(method, f"{settings.task_vikunja_api_prefix.rstrip('/')}{path}", headers=headers, json=body)
        response.raise_for_status()
        if not response.content:
            return {}
        return response.json()


def _resolve_token() -> str:
    if settings.task_vikunja_token:
        return settings.task_vikunja_token.strip()
    if settings.task_vikunja_token_file:
        try:
            with open(settings.task_vikunja_token_file, "r", encoding="utf-8") as handle:
                return handle.read().strip()
        except OSError:
            return ""
    return ""


def _task_occurred_at(task: dict[str, Any], *, canonical_type: str) -> datetime:
    if canonical_type == "task.created":
        created = _parse_dt(task.get("created"))
        if created is not None:
            return created
    updated = _parse_dt(task.get("updated"))
    if updated is not None:
        return updated
    created = _parse_dt(task.get("created"))
    if created is not None:
        return created
    return datetime.now(UTC)


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except Exception:
        return None


def _event_exists(db: Session, event_id: str) -> bool:
    existing = db.execute(select(FamilyEventRecord.event_id).where(FamilyEventRecord.event_id == event_id)).first()
    return existing is not None


def _int_or_none(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except Exception:
        return None
