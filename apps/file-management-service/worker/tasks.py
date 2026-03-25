from __future__ import annotations

from app.core.db import SessionLocal
from app.services.discovery import run_configured_discovery_scans
from app.services.jobs import process_pending_jobs
from worker.celery_app import celery_app


@celery_app.task
def process_followup_jobs():
    db = SessionLocal()
    try:
        result = process_pending_jobs(db, limit=25)
        db.commit()
        result["job"] = "process_followup_jobs"
        return result
    finally:
        db.close()


@celery_app.task
def run_discovery_scans():
    db = SessionLocal()
    try:
        result = run_configured_discovery_scans(db)
        db.commit()
        result["job"] = "run_discovery_scans"
        return result
    finally:
        db.close()
