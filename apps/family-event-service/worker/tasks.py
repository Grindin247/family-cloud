from __future__ import annotations

from app.core.db import SessionLocal
from app.services.vikunja_events import ensure_project_webhooks, reconcile_recent_task_events
from agents.common.family_events import publish_event as publish_family_event
from worker.celery_app import celery_app


@celery_app.task
def ensure_vikunja_project_webhooks():
    try:
        result = ensure_project_webhooks()
        result["job"] = "vikunja_project_webhooks"
        return result
    except Exception as exc:
        return {"job": "vikunja_project_webhooks", "status": "error", "error": str(exc)}


@celery_app.task
def reconcile_vikunja_task_events():
    db = SessionLocal()
    try:
        result = reconcile_recent_task_events(db)
        emitted = 0
        for event in result.get("events", []):
            try:
                publish_family_event(event)
                emitted += 1
            except Exception:
                continue
        result["job"] = "vikunja_task_event_reconcile"
        result["emitted"] = emitted
        return result
    finally:
        db.close()
