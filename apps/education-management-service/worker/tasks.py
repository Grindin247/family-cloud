from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select

from app.core.config import settings
from app.core.db import SessionLocal
from app.models.education import Assignment, JournalEntry, LearnerProfile, PracticeRepetition, ProgressSnapshot, QuizSession
from app.services.education import refresh_snapshots, try_publish_event_rows
from worker.celery_app import celery_app


def _headers() -> dict[str, str]:
    return {"X-Internal-Admin-Token": settings.question_internal_admin_token or settings.internal_admin_token}


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC).isoformat()
    return value.astimezone(UTC).isoformat()


def _upsert_question(family_id: int, payload: dict[str, object]) -> None:
    httpx.post(
        f"{settings.question_api_base_url.rstrip('/')}/families/{family_id}/questions",
        headers=_headers(),
        json=payload,
        timeout=20.0,
    ).raise_for_status()


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


@celery_app.task
def generate_pending_education_questions():
    db = SessionLocal()
    now = datetime.now(UTC)
    practice_gap_cutoff = now - timedelta(days=settings.education_question_practice_gap_days)
    journal_gap_cutoff = now - timedelta(days=settings.education_question_journal_gap_days)
    results = {"job": "generate_pending_education_questions", "learners": 0, "questions_upserted": 0}
    try:
        learners = db.execute(select(LearnerProfile)).scalars().all()
        for learner in learners:
            learner_id = str(learner.learner_id)
            label = learner.display_name
            family_id = learner.family_id
            results["learners"] += 1

            overdue_assignments = db.execute(
                select(Assignment).where(
                    Assignment.family_id == family_id,
                    Assignment.learner_id == learner.learner_id,
                    Assignment.completed_at.is_(None),
                    Assignment.due_at.is_not(None),
                    Assignment.due_at < now,
                )
            ).scalars().all()
            for assignment in overdue_assignments[:4]:
                prompt = f"{label} has an overdue assignment: {assignment.title}. Should this be completed, rescheduled, or dismissed?"
                _upsert_question(
                    family_id,
                    {
                        "domain": "education",
                        "source_agent": "EducationAgent",
                        "topic": f"Overdue assignment: {assignment.title}",
                        "summary": prompt,
                        "prompt": prompt,
                        "urgency": "high",
                        "category": "assignment_overdue",
                        "topic_type": "assignment_overdue",
                        "dedupe_key": f"education:assignment_overdue:{assignment.assignment_id}",
                        "due_at": _iso(assignment.due_at),
                        "context": {
                            "learner_id": learner_id,
                            "learner_name": label,
                            "assignment_id": str(assignment.assignment_id),
                            "status": assignment.status,
                        },
                        "artifact_refs": [{"type": "assignment", "id": str(assignment.assignment_id)}],
                    },
                )
                results["questions_upserted"] += 1

            latest_practice = db.execute(
                select(PracticeRepetition)
                .where(
                    PracticeRepetition.family_id == family_id,
                    PracticeRepetition.learner_id == learner.learner_id,
                )
                .order_by(PracticeRepetition.occurred_at.desc())
                .limit(1)
            ).scalar_one_or_none()
            if latest_practice is None or latest_practice.occurred_at < practice_gap_cutoff:
                prompt = f"It has been a while since {label} logged practice. Is there something worth recording or reviewing?"
                _upsert_question(
                    family_id,
                    {
                        "domain": "education",
                        "source_agent": "EducationAgent",
                        "topic": f"Practice check-in for {label}",
                        "summary": prompt,
                        "prompt": prompt,
                        "urgency": "medium",
                        "category": "practice_gap",
                        "topic_type": "practice_gap",
                        "dedupe_key": f"education:practice_gap:{learner_id}",
                        "context": {
                            "learner_id": learner_id,
                            "learner_name": label,
                            "last_practice_at": _iso(latest_practice.occurred_at) if latest_practice else None,
                        },
                        "artifact_refs": [{"type": "learner", "id": learner_id}],
                    },
                )
                results["questions_upserted"] += 1

            latest_journal = db.execute(
                select(JournalEntry)
                .where(
                    JournalEntry.family_id == family_id,
                    JournalEntry.learner_id == learner.learner_id,
                )
                .order_by(JournalEntry.occurred_at.desc())
                .limit(1)
            ).scalar_one_or_none()
            if latest_journal is None or latest_journal.occurred_at < journal_gap_cutoff:
                prompt = f"{label} has not logged a recent journal reflection. Is there a short update worth capturing?"
                _upsert_question(
                    family_id,
                    {
                        "domain": "education",
                        "source_agent": "EducationAgent",
                        "topic": f"Journal check-in for {label}",
                        "summary": prompt,
                        "prompt": prompt,
                        "urgency": "medium",
                        "category": "journal_gap",
                        "topic_type": "journal_gap",
                        "dedupe_key": f"education:journal_gap:{learner_id}",
                        "context": {
                            "learner_id": learner_id,
                            "learner_name": label,
                            "last_journal_at": _iso(latest_journal.occurred_at) if latest_journal else None,
                        },
                        "artifact_refs": [{"type": "learner", "id": learner_id}],
                    },
                )
                results["questions_upserted"] += 1

            recent_quiz = db.execute(
                select(QuizSession)
                .where(
                    QuizSession.family_id == family_id,
                    QuizSession.learner_id == learner.learner_id,
                    QuizSession.completed_at.is_not(None),
                    QuizSession.max_score.is_not(None),
                    QuizSession.max_score > 0,
                    QuizSession.created_at >= now - timedelta(days=14),
                )
                .order_by(QuizSession.completed_at.desc())
                .limit(1)
            ).scalar_one_or_none()
            if recent_quiz and recent_quiz.total_score is not None and recent_quiz.max_score:
                percent = (float(recent_quiz.total_score) / float(recent_quiz.max_score)) * 100.0
                if percent < settings.education_question_low_mastery_threshold:
                    prompt = f"{label} scored {percent:.0f}% on '{recent_quiz.title}'. Would a retry or review session help?"
                    _upsert_question(
                        family_id,
                        {
                            "domain": "education",
                            "source_agent": "EducationAgent",
                            "topic": f"Quiz follow-up: {recent_quiz.title}",
                            "summary": prompt,
                            "prompt": prompt,
                            "urgency": "high",
                            "category": "quiz_followup",
                            "topic_type": "quiz_followup",
                            "dedupe_key": f"education:quiz_followup:{recent_quiz.quiz_id}",
                            "context": {
                                "learner_id": learner_id,
                                "learner_name": label,
                                "quiz_id": str(recent_quiz.quiz_id),
                                "percent": percent,
                            },
                            "artifact_refs": [{"type": "quiz", "id": str(recent_quiz.quiz_id)}],
                        },
                    )
                    results["questions_upserted"] += 1

            latest_snapshot = db.execute(
                select(ProgressSnapshot)
                .where(
                    ProgressSnapshot.family_id == family_id,
                    ProgressSnapshot.learner_id == learner.learner_id,
                    ProgressSnapshot.as_of_date >= (now.date() - timedelta(days=7)),
                )
                .order_by(ProgressSnapshot.as_of_date.desc())
                .limit(1)
            ).scalar_one_or_none()
            if latest_snapshot:
                latest_score = float(latest_snapshot.latest_score or latest_snapshot.avg_score_30d or 0.0)
                if latest_score and latest_score < settings.education_question_low_mastery_threshold:
                    prompt = f"{label} looks below the recent mastery target in one learning area. Want a low-pressure review plan?"
                    _upsert_question(
                        family_id,
                        {
                            "domain": "education",
                            "source_agent": "EducationAgent",
                            "topic": f"Review suggestion for {label}",
                            "summary": prompt,
                            "prompt": prompt,
                            "urgency": "medium",
                            "category": "low_mastery_review",
                            "topic_type": "low_mastery_review",
                            "dedupe_key": f"education:low_mastery:{learner_id}:{latest_snapshot.scope_key}",
                            "context": {
                                "learner_id": learner_id,
                                "learner_name": label,
                                "scope_key": latest_snapshot.scope_key,
                                "latest_score": latest_score,
                            },
                            "artifact_refs": [{"type": "progress_snapshot", "id": str(latest_snapshot.snapshot_id)}],
                        },
                    )
                    results["questions_upserted"] += 1

        return results
    finally:
        db.close()
