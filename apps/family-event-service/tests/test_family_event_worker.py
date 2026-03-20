import json

import pytest

from agents.common.family_events import build_event, make_privacy
from conftest import TestingSessionLocal

from app.models.family_events import FamilyEventDeadLetter, FamilyEventRecord


@pytest.mark.asyncio
async def test_process_raw_event_ingests(monkeypatch):
    from worker import family_events_worker

    event = build_event(
        family_id=2,
        domain="task",
        event_type="task.completed",
        actor={"actor_type": "user", "actor_id": "admin@example.com"},
        subject={"subject_type": "task", "subject_id": "7"},
        payload={"task_id": 7, "title": "Call plumber", "completed_by": "admin@example.com"},
        source={"agent_id": "TaskAgent", "runtime": "backend"},
        privacy=make_privacy(),
    )
    monkeypatch.setattr(family_events_worker, "SessionLocal", TestingSessionLocal)
    status, event_id = await family_events_worker.process_raw_event(raw_text=json.dumps(event), subject="family.events.task")
    db = TestingSessionLocal()
    try:
        assert status == "ingested"
        assert event_id == event["event_id"]
        assert db.query(FamilyEventRecord).count() == 1
    finally:
        db.close()


@pytest.mark.asyncio
async def test_process_raw_event_dead_letters(monkeypatch):
    from worker import family_events_worker

    event = build_event(
        family_id=2,
        domain="task",
        event_type="task.completed",
        actor={"actor_type": "user", "actor_id": "admin@example.com"},
        subject={"subject_type": "task", "subject_id": "7"},
        payload={"task_id": 7, "title": "Call plumber"},
        source={"agent_id": "TaskAgent", "runtime": "backend"},
        privacy=make_privacy(),
    )
    monkeypatch.setattr(family_events_worker, "SessionLocal", TestingSessionLocal)
    status, event_id = await family_events_worker.process_raw_event(raw_text=json.dumps(event), subject="family.events.task")
    db = TestingSessionLocal()
    try:
        assert status == "dead_lettered"
        assert event_id is None
        assert db.query(FamilyEventDeadLetter).count() == 1
    finally:
        db.close()
