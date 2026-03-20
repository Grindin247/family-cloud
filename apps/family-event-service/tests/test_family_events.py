from datetime import UTC, datetime
from pathlib import Path

from agents.common.family_events import build_event, make_privacy

from app.models.family_events import FamilyEventDeadLetter, FamilyEventRecord
from app.services.family_events import dead_letter_family_event, export_family_events_jsonl, ingest_family_event


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


def test_ingest_family_event(db_session):
    event = _sample_event(family_id=2)
    event["actor"]["person_id"] = "person-admin"
    event["subject"]["person_id"] = "person-subject"
    record = ingest_family_event(db_session, event, subject="family.events.decision")
    db_session.commit()
    assert isinstance(record, FamilyEventRecord)
    assert record.event_type == "decision.created"
    assert record.actor_person_id == "person-admin"
    assert record.subject_person_id == "person-subject"
    assert record.legacy_usage_event_id is None
    assert record.legacy_playback_event_id is None


def test_ingest_invalid_event_goes_to_dead_letter(db_session):
    bad = _sample_event(family_id=2, event_type="decision.score_calculated", payload={"decision_id": 42})
    try:
        ingest_family_event(db_session, bad, subject="family.events.decision")
    except Exception as exc:
        dead_letter_family_event(db_session, subject="family.events.decision", raw_event=bad, error=exc)
        db_session.commit()
    row = db_session.query(FamilyEventDeadLetter).one()
    assert row.subject == "family.events.decision"
    assert row.event_id == bad["event_id"]


def test_family_events_api_and_analytics(client, db_session):
    decision = _sample_event(family_id=2)
    decision_scored = _sample_event(
        family_id=2,
        event_type="decision.score_calculated",
        payload={"decision_id": 42, "title": "Move school", "score_type": "goal_alignment", "score_value": 0.8},
    )
    task_created = build_event(
        family_id=2,
        domain="task",
        event_type="task.created",
        actor={"actor_type": "user", "actor_id": "admin@example.com"},
        subject={"subject_type": "task", "subject_id": "91"},
        payload={"task_id": 91, "title": "Call plumber"},
        source={"agent_id": "TaskAgent", "runtime": "openclaw-subagent", "session_id": "t1"},
        privacy=make_privacy(),
        tags=["household"],
        occurred_at=datetime(2026, 3, 10, 13, 0, tzinfo=UTC),
        recorded_at=datetime(2026, 3, 10, 13, 0, tzinfo=UTC),
    )
    task = build_event(
        family_id=2,
        domain="task",
        event_type="task.completed",
        actor={"actor_type": "user", "actor_id": "admin@example.com"},
        subject={"subject_type": "task", "subject_id": "91"},
        payload={"task_id": 91, "title": "Call plumber", "completed_by": "admin@example.com"},
        source={"agent_id": "TaskAgent", "runtime": "openclaw-subagent", "session_id": "t1"},
        privacy=make_privacy(),
        tags=["household"],
        occurred_at=datetime(2026, 3, 16, 13, 0, tzinfo=UTC),
        recorded_at=datetime(2026, 3, 16, 13, 0, tzinfo=UTC),
    )
    overdue = build_event(
        family_id=2,
        domain="task",
        event_type="task.overdue",
        actor={"actor_type": "system", "actor_id": "scheduler"},
        subject={"subject_type": "task", "subject_id": "92"},
        payload={"task_id": 92, "title": "Schedule dentist"},
        source={"agent_id": "TaskAgent", "runtime": "backend", "session_id": "t2"},
        privacy=make_privacy(),
        tags=["household"],
        occurred_at=datetime(2026, 3, 12, 8, 0, tzinfo=UTC),
        recorded_at=datetime(2026, 3, 13, 12, 0, tzinfo=UTC),
    )
    note = build_event(
        family_id=2,
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
        (decision_scored, "family.events.decision"),
        (task_created, "family.events.task"),
        (task, "family.events.task"),
        (overdue, "family.events.task"),
        (note, "family.events.file"),
    ]:
        ingest_family_event(db_session, item, subject=subject)
    db_session.commit()

    events = client.get("/v1/events?family_id=2", headers={"X-Dev-User": "admin@example.com"})
    assert events.status_code == 200
    assert len(events.json()) == 6

    filtered = client.get("/v1/events?family_id=2&tag=household&domain=task", headers={"X-Dev-User": "admin@example.com"})
    assert filtered.status_code == 200
    assert len(filtered.json()) == 3

    timeline = client.get("/v1/timeline?family_id=2", headers={"X-Dev-User": "admin@example.com"})
    assert timeline.status_code == 200
    assert timeline.json()[0]["event_type"] == "note.created"

    counts = client.get("/v1/analytics/counts?family_id=2", headers={"X-Dev-User": "admin@example.com"})
    metrics = {item["metric"]: item["value"] for item in counts.json()}
    assert metrics["events.count"] == 6.0
    assert metrics["church.notes.count"] == 1.0

    series = client.get("/v1/analytics/time-series?family_id=2&metric=tasks.completed.count&bucket=day", headers={"X-Dev-User": "admin@example.com"})
    assert series.status_code == 200
    assert series.json()["points"][0]["value"] == 1.0

    summary = client.get("/v1/analytics/domain-summary?family_id=2", headers={"X-Dev-User": "admin@example.com"})
    summary_items = {item["domain"]: item for item in summary.json()}
    assert summary_items["task"]["total_events"] == 3

    comparison = client.get(
        "/v1/analytics/compare-periods?family_id=2&metric=tasks.completed.count&baseline_start=2026-03-01T00:00:00Z&baseline_end=2026-03-11T23:59:59Z&current_start=2026-03-12T00:00:00Z&current_end=2026-03-16T23:59:59Z",
        headers={"X-Dev-User": "admin@example.com"},
    )
    assert comparison.status_code == 200
    assert comparison.json()["current_value"] == 1.0

    sequences = client.get(
        f"/v1/analytics/sequences?family_id=2&anchor_event_id={decision['event_id']}&before_limit=1&after_limit=2",
        headers={"X-Dev-User": "admin@example.com"},
    )
    assert sequences.status_code == 200
    assert sequences.json()["anchor"]["event_type"] == "decision.created"

    top_tags = client.get("/v1/analytics/top-tags?family_id=2&limit=5", headers={"X-Dev-User": "admin@example.com"})
    assert any(item["label"] == "household" and item["source"] == "tag" for item in top_tags.json())

    data_quality = client.get("/v1/analytics/data-quality?family_id=2", headers={"X-Dev-User": "admin@example.com"})
    body = data_quality.json()
    assert body["covered_domains"] == ["decision", "note", "task"]
    assert "file" in body["missing_domains"]


def test_family_event_ingest_route(client):
    payload = _sample_event(family_id=2, event_type="decision.created")
    response = client.post("/v1/events", json=payload, headers={"X-Dev-User": "admin@example.com"})
    assert response.status_code == 201
    assert response.json()["event"]["event_type"] == "decision.created"


def test_export_family_events_jsonl(db_session, tmp_path: Path):
    event = _sample_event(family_id=2)
    ingest_family_event(db_session, event, subject="family.events.decision")
    output_path = tmp_path / "export.jsonl"
    job = export_family_events_jsonl(db_session, family_id=2, actor="tester@example.com", output_path=str(output_path))
    db_session.commit()
    assert job.status == "completed"
    assert output_path.exists()
