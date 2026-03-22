from __future__ import annotations

from app.core.db import SessionLocal
from app.services.questions import cleanup_question_backlog, expire_questions, refresh_engagement_windows, release_expired_claims
from worker.celery_app import celery_app


@celery_app.task
def expire_stale_questions():
    db = SessionLocal()
    try:
        released = release_expired_claims(db, actor="question-worker")
        expired = expire_questions(db, actor="question-worker")
        db.commit()
        return {"job": "expire_stale_questions", "released_claims": released, "expired": expired}
    finally:
        db.close()


@celery_app.task
def cleanup_question_backlog_task():
    db = SessionLocal()
    try:
        result = cleanup_question_backlog(db, actor="question-worker")
        db.commit()
        result["job"] = "cleanup_question_backlog"
        return result
    finally:
        db.close()


@celery_app.task
def refresh_question_engagement_windows():
    db = SessionLocal()
    try:
        result = refresh_engagement_windows(db)
        db.commit()
        result["job"] = "refresh_question_engagement_windows"
        return result
    finally:
        db.close()
