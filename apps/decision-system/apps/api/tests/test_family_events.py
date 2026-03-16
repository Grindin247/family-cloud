from datetime import UTC, datetime
from pathlib import Path

from agents.common.family_events import build_event, make_privacy
from app.models.entities import Family, FamilyMember, RoleEnum
from app.models.family_events import FamilyEventDeadLetter, FamilyEventRecord
from app.services.family_events import dead_letter_family_event, export_family_events_jsonl, ingest_family_event


def _seed_family(db_session):
    family = Family(name="Smith")
    db_session.add(family)
    db_session.flush()
    member = FamilyMember(family_id=family.id, email="admin@example.com", display_name="Admin", role=RoleEnum.admin)
    db_session.add(member)
    db_session.commit()
    return family.id


def _sample_event(*, family_id: int, event_type: str = "decision.created", domain: str = "decision", subject_type: str = "decision", subject_id: str = "42", payload=None):
    return build_event(
        family_id=family_id,
        domain=domain,
        event_type=event_type,
        actor={"actor_type": "user", "actor_id": "admin@example.com"},
        subject={"subject_type": subject_type, "subject_id": subject_id},
        payload=payload or {"decision_id": 42, "title": "Move school"},
        source={"agent_id": "DecisionAgent", "runtime": "openclaw-subagent", "session_id": "s1"},
        privacy=make_privacy(),
        occurred_at=datetime(2026, 3, 16, 12, 0, tzinfo=UTC),
        recorded_at=datetime(2026, 3, 16, 12, 0, tzinfo=UTC),
    )


def test_ingest_family_event_bridges_to_legacy(db_session):
    family_id = _seed_family(db_session)
    event = _sample_event(family_id=family_id)

    record = ingest_family_event(db_session, event, subject="family.events.decision")
    db_session.commit()

    assert isinstance(record, FamilyEventRecord)
    assert record.event_type == "decision.created"
    assert record.legacy_usage_event_id is not None
    assert record.legacy_playback_event_id is not None


def test_ingest_invalid_event_goes_to_dead_letter(db_session):
    family_id = _seed_family(db_session)
    bad = _sample_event(
        family_id=family_id,
        event_type="decision.score_calculated",
        payload={"decision_id": 42},
    )

    try:
        ingest_family_event(db_session, bad, subject="family.events.decision")
    except Exception as exc:
        dead_letter_family_event(db_session, subject="family.events.decision", raw_event=bad, error=exc)
        db_session.commit()

    row = db_session.query(FamilyEventDeadLetter).one()
    assert row.subject == "family.events.decision"
    assert row.event_id == bad["event_id"]


def test_family_events_api_and_analytics(client, db_session):
    family_id = _seed_family(db_session)
    decision = _sample_event(family_id=family_id)
    task = build_event(
        family_id=family_id,
        domain="task",
        event_type="task.completed",
        actor={"actor_type": "user", "actor_id": "admin@example.com"},
        subject={"subject_type": "task", "subject_id": "91"},
        payload={"task_id": 91, "title": "Call plumber", "completed_by": "admin@example.com"},
        source={"agent_id": "TaskAgent", "runtime": "openclaw-subagent", "session_id": "t1"},
        privacy=make_privacy(),
        occurred_at=datetime(2026, 3, 16, 13, 0, tzinfo=UTC),
        recorded_at=datetime(2026, 3, 16, 13, 0, tzinfo=UTC),
    )
    note = build_event(
        family_id=family_id,
        domain="note",
        event_type="note.created",
        actor={"actor_type": "user", "actor_id": "admin@example.com"},
        subject={"subject_type": "note", "subject_id": "/Notes/church.md"},
        payload={"path": "/Notes/church.md", "note_type": "church", "title": "Sunday notes"},
        source={"agent_id": "FileAgent", "runtime": "backend", "session_id": "f1"},
        privacy=make_privacy(),
        tags=["church"],
        occurred_at=datetime(2026, 3, 16, 14, 0, tzinfo=UTC),
        recorded_at=datetime(2026, 3, 16, 14, 0, tzinfo=UTC),
    )
    for item, subject in [
        (decision, "family.events.decision"),
        (task, "family.events.task"),
        (note, "family.events.file"),
    ]:
        ingest_family_event(db_session, item, subject=subject)
    db_session.commit()

    headers = {"X-Dev-User": "admin@example.com"}
    events = client.get(f"/v1/events?family_id={family_id}", headers=headers)
    assert events.status_code == 200
    assert len(events.json()) == 3

    timeline = client.get(f"/v1/timeline?family_id={family_id}", headers=headers)
    assert timeline.status_code == 200
    assert timeline.json()[0]["event_type"] == "note.created"

    counts = client.get(f"/v1/analytics/counts?family_id={family_id}", headers=headers)
    assert counts.status_code == 200
    metrics = {item["metric"]: item["value"] for item in counts.json()}
    assert metrics["notes.created.count"] == 1.0
    assert metrics["tasks.completed.count"] == 1.0
    assert metrics["decisions.created.count"] == 1.0
    assert metrics["church.notes.count"] == 1.0

    series = client.get(
        f"/v1/analytics/time-series?family_id={family_id}&metric=tasks.completed.count&bucket=day",
        headers=headers,
    )
    assert series.status_code == 200
    assert series.json()["points"][0]["value"] == 1.0


def test_family_event_ingest_route(client, db_session):
    family_id = _seed_family(db_session)
    headers = {"X-Dev-User": "admin@example.com"}
    payload = _sample_event(family_id=family_id, event_type="decision.created")

    response = client.post("/v1/events", json=payload, headers=headers)

    assert response.status_code == 201
    body = response.json()
    assert body["event"]["event_type"] == "decision.created"
    assert body["event"]["family_id"] == family_id
    assert body["legacy_usage_event_id"] is not None


def test_family_event_export_jsonl(db_session, tmp_path: Path):
    family_id = _seed_family(db_session)
    event = _sample_event(family_id=family_id, subject_id="export-1")
    ingest_family_event(db_session, event, subject="family.events.decision")
    db_session.commit()

    output = tmp_path / "family-events.jsonl"
    job = export_family_events_jsonl(
        db_session,
        family_id=family_id,
        actor="admin@example.com",
        output_path=str(output),
    )
    db_session.commit()

    assert job.status == "completed"
    contents = output.read_text(encoding="utf-8").strip().splitlines()
    assert len(contents) == 1
    assert "admin@example.com" not in contents[0]
    assert '"family_pseudo_id":"fam_' in contents[0]
