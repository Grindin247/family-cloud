from __future__ import annotations

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models.education import LearnerProfile
from app.services.education import refresh_snapshots, try_publish_event_rows
from worker.celery_app import celery_app


@celery_app.task
def publish_pending_education_events():
    db = SessionLocal()
    try:
        result = try_publish_event_rows(db)
        result["job"] = "publish_pending_education_events"
        return result
    finally:
        db.close()


@celery_app.task
def refresh_current_snapshots():
    db = SessionLocal()
    try:
        learners = db.execute(select(LearnerProfile)).scalars().all()
        refreshed = 0
        for learner in learners:
            refresh_snapshots(
                db,
                family_id=learner.family_id,
                learner_id=learner.learner_id,
                domain_id=None,
                skill_id=None,
            )
            refreshed += 1
        db.commit()
        return {"job": "refresh_current_snapshots", "refreshed": refreshed}
    finally:
        db.close()
