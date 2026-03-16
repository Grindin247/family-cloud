from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from agents.common.family_events import build_event, make_privacy
from app.models.entities import Family, FamilyMember, RoleEnum
from app.models.family_events import FamilyEventDeadLetter, FamilyEventRecord
from conftest import TestingSessionLocal

WORKER_DIR = Path(__file__).resolve().parents[2] / "worker"
if str(WORKER_DIR) not in sys.path:
    sys.path.insert(0, str(WORKER_DIR))


def _seed_family(db_session) -> int:
    family = Family(name="Worker Family")
    db_session.add(family)
    db_session.flush()
    member = FamilyMember(family_id=family.id, email="worker@example.com", display_name="Worker", role=RoleEnum.admin)
    db_session.add(member)
    db_session.commit()
    return family.id


@pytest.mark.asyncio
async def test_worker_processes_valid_family_event(db_session, monkeypatch):
    from worker import family_events_worker

    family_id = _seed_family(db_session)
    monkeypatch.setattr(family_events_worker, "SessionLocal", TestingSessionLocal)
    event = build_event(
        family_id=family_id,
        domain="file",
        event_type="file.indexed",
        actor={"actor_type": "user", "actor_id": "worker@example.com"},
        subject={"subject_type": "file", "subject_id": "file-123"},
        payload={"file_id": "file-123", "path": "/Family/file.txt", "title": "file.txt"},
        source={"agent_id": "FileAgent", "runtime": "backend"},
        privacy=make_privacy(),
    )

    status, event_id = await family_events_worker.process_raw_event(
        raw_text=json.dumps(event),
        subject="family.events.file",
    )

    assert status == "ingested"
    row = db_session.query(FamilyEventRecord).filter(FamilyEventRecord.event_id == event_id).one()
    assert row.event_type == "file.indexed"


@pytest.mark.asyncio
async def test_worker_dead_letters_invalid_family_event(db_session, monkeypatch):
    from worker import family_events_worker

    family_id = _seed_family(db_session)
    monkeypatch.setattr(family_events_worker, "SessionLocal", TestingSessionLocal)
    bad_event = build_event(
        family_id=family_id,
        domain="decision",
        event_type="decision.score_calculated",
        actor={"actor_type": "user", "actor_id": "worker@example.com"},
        subject={"subject_type": "decision", "subject_id": "d-1"},
        payload={"decision_id": "d-1"},
        source={"agent_id": "DecisionAgent", "runtime": "backend"},
        privacy=make_privacy(),
    )

    status, event_id = await family_events_worker.process_raw_event(
        raw_text=json.dumps(bad_event),
        subject="family.events.decision",
    )

    assert status == "dead_lettered"
    row = db_session.query(FamilyEventDeadLetter).filter(FamilyEventDeadLetter.event_id == event_id).one()
    assert row.subject == "family.events.decision"
