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


def test_ingest_question_purged_summary_event(db_session):
    event = build_event(
        family_id=2,
        domain="question",
        event_type="question.purged",
        actor={"actor_type": "system", "actor_id": "system"},
        subject={"subject_type": "question", "subject_id": "purge:2:test"},
        payload={"title": "Question backlog purge", "purged_count": 3},
        source={"agent_id": "QuestionService", "runtime": "backend", "channel": "backfill"},
        privacy=make_privacy(),
        occurred_at=datetime(2026, 3, 16, 12, 0, tzinfo=UTC),
        recorded_at=datetime(2026, 3, 16, 12, 0, tzinfo=UTC),
    )
    record = ingest_family_event(db_session, event, subject="family.events.question")
    db_session.commit()
    assert record.event_type == "question.purged"
    assert record.domain == "question"


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


def _viewer_context(*, family_id: int, person_id: str, is_family_admin: bool, primary_email: str):
    return {
        "family_id": family_id,
        "family_slug": "callender-family",
        "person_id": person_id,
        "actor_person_id": person_id,
        "target_person_id": person_id,
        "is_family_admin": is_family_admin,
        "primary_email": primary_email,
        "directory_account_id": None,
        "member_id": 1,
    }


def _viewer_person(*, family_id: int, person_id: str, display_name: str, email: str, is_admin: bool = False):
    return {
        "person_id": person_id,
        "family_id": family_id,
        "legacy_member_id": None,
        "canonical_name": display_name,
        "display_name": display_name,
        "role_in_family": "admin" if is_admin else "viewer",
        "is_admin": is_admin,
        "status": "active",
        "aliases": [],
        "accounts": {"email": [email]},
    }


def _patch_viewer_dependencies(monkeypatch, *, me_payload, context_payload, persons_payload):
    monkeypatch.setattr("app.routers.family_events.get_me", lambda **_: me_payload)
    monkeypatch.setattr("app.routers.family_events.get_family_context", lambda **_: context_payload)
    monkeypatch.setattr("app.routers.family_events.get_family_persons", lambda **_: persons_payload)


def test_viewer_me_route_returns_memberships(client, monkeypatch):
    _patch_viewer_dependencies(
        monkeypatch,
        me_payload={
            "authenticated": True,
            "email": "viewer@example.com",
            "memberships": [
                {"family_id": 2, "family_name": "Callender Family", "member_id": 7, "person_id": "person-viewer", "role": "viewer"}
            ],
        },
        context_payload=_viewer_context(family_id=2, person_id="person-viewer", is_family_admin=False, primary_email="viewer@example.com"),
        persons_payload=[_viewer_person(family_id=2, person_id="person-viewer", display_name="Viewer", email="viewer@example.com")],
    )

    response = client.get("/v1/me", headers={"X-Dev-User": "viewer@example.com"})
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "viewer@example.com"
    assert body["memberships"][0]["family_name"] == "Callender Family"


def test_viewer_context_route_returns_actor_and_persons(client, monkeypatch):
    persons = [
        _viewer_person(family_id=2, person_id="person-admin", display_name="Admin", email="admin@example.com", is_admin=True),
        _viewer_person(family_id=2, person_id="person-child", display_name="Child", email="child@example.com"),
    ]
    _patch_viewer_dependencies(
        monkeypatch,
        me_payload={"authenticated": True, "email": "admin@example.com", "memberships": []},
        context_payload=_viewer_context(family_id=2, person_id="person-admin", is_family_admin=True, primary_email="admin@example.com"),
        persons_payload=persons,
    )

    response = client.get("/v1/families/2/viewer-context", headers={"X-Dev-User": "admin@example.com"})
    assert response.status_code == 200
    body = response.json()
    assert body["is_family_admin"] is True
    assert len(body["persons"]) == 2
    assert body["persons"][1]["display_name"] == "Child"


def test_viewer_search_defaults_non_admin_to_own_events(client, db_session, monkeypatch):
    current = _sample_event(family_id=2)
    current["actor"]["person_id"] = "person-viewer"
    other = _sample_event(family_id=2, subject_id="99")
    other["actor"]["person_id"] = "person-other"
    target = _sample_event(family_id=2, event_type="decision.updated", subject_id="100", payload={"decision_id": 100, "title": "Camp", "target_person_id": "person-viewer"})
    for item in (current, other, target):
        ingest_family_event(db_session, item, subject="family.events.decision")
    db_session.commit()

    _patch_viewer_dependencies(
        monkeypatch,
        me_payload={"authenticated": True, "email": "viewer@example.com", "memberships": []},
        context_payload=_viewer_context(family_id=2, person_id="person-viewer", is_family_admin=False, primary_email="viewer@example.com"),
        persons_payload=[
            _viewer_person(family_id=2, person_id="person-viewer", display_name="Viewer", email="viewer@example.com"),
            _viewer_person(family_id=2, person_id="person-other", display_name="Other", email="other@example.com"),
        ],
    )

    response = client.get("/v1/events/search?family_id=2", headers={"X-Dev-User": "viewer@example.com"})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert {item["subject_id"] for item in body["items"]} == {"42", "100"}


def test_viewer_search_rejects_non_admin_cross_member_scope(client, monkeypatch):
    _patch_viewer_dependencies(
        monkeypatch,
        me_payload={"authenticated": True, "email": "viewer@example.com", "memberships": []},
        context_payload=_viewer_context(family_id=2, person_id="person-viewer", is_family_admin=False, primary_email="viewer@example.com"),
        persons_payload=[_viewer_person(family_id=2, person_id="person-viewer", display_name="Viewer", email="viewer@example.com")],
    )

    response = client.get("/v1/events/search?family_id=2&member_scope=all", headers={"X-Dev-User": "viewer@example.com"})
    assert response.status_code == 403
    assert response.json()["detail"] == "admin role required for cross-member event access"


def test_viewer_search_admin_defaults_to_all_and_supports_person_fallback(client, db_session, monkeypatch):
    child_event = build_event(
        family_id=2,
        domain="task",
        event_type="task.created",
        actor={"actor_type": "user", "actor_id": "child@example.com"},
        subject={"subject_type": "task", "subject_id": "child-task"},
        payload={"task_id": 5, "title": "Kid chore"},
        source={"agent_id": "TaskAgent", "runtime": "backend", "session_id": "viewer-admin"},
        privacy=make_privacy(),
        occurred_at=datetime(2026, 3, 16, 12, 0, tzinfo=UTC),
        recorded_at=datetime(2026, 3, 16, 12, 0, tzinfo=UTC),
    )
    child_event["actor"] = {"actor_type": "user", "actor_id": "child@example.com"}
    admin_event = build_event(
        family_id=2,
        domain="task",
        event_type="task.completed",
        actor={"actor_type": "user", "actor_id": "admin@example.com", "person_id": "person-admin"},
        subject={"subject_type": "task", "subject_id": "admin-task"},
        payload={"task_id": 6, "title": "Parent chore", "completed_by": "admin@example.com"},
        source={"agent_id": "TaskAgent", "runtime": "backend", "session_id": "viewer-admin"},
        privacy=make_privacy(),
        occurred_at=datetime(2026, 3, 16, 13, 0, tzinfo=UTC),
        recorded_at=datetime(2026, 3, 16, 13, 0, tzinfo=UTC),
    )
    admin_event["actor"]["person_id"] = "person-admin"
    for item, subject in ((child_event, "family.events.task"), (admin_event, "family.events.task")):
        ingest_family_event(db_session, item, subject=subject)
    db_session.commit()

    _patch_viewer_dependencies(
        monkeypatch,
        me_payload={"authenticated": True, "email": "admin@example.com", "memberships": []},
        context_payload=_viewer_context(family_id=2, person_id="person-admin", is_family_admin=True, primary_email="admin@example.com"),
        persons_payload=[
            _viewer_person(family_id=2, person_id="person-admin", display_name="Admin", email="admin@example.com", is_admin=True),
            _viewer_person(family_id=2, person_id="person-child", display_name="Child", email="child@example.com"),
        ],
    )

    response = client.get("/v1/events/search?family_id=2", headers={"X-Dev-User": "admin@example.com"})
    assert response.status_code == 200
    assert response.json()["total"] == 2

    filtered = client.get(
        "/v1/events/search?family_id=2&member_scope=person&person_id=person-child",
        headers={"X-Dev-User": "admin@example.com"},
    )
    assert filtered.status_code == 200
    body = filtered.json()
    assert body["total"] == 1
    assert body["items"][0]["actor_id"] == "child@example.com"


def test_viewer_search_matches_wildcards_and_paginates(client, db_session, monkeypatch):
    first = build_event(
        family_id=2,
        domain="task",
        event_type="task.created",
        actor={"actor_type": "user", "actor_id": "viewer@example.com", "person_id": "person-viewer"},
        subject={"subject_type": "task", "subject_id": "501"},
        payload={"task_id": 501, "title": "Call plumber"},
        source={"agent_id": "TaskAgent", "runtime": "backend", "session_id": "viewer-search"},
        privacy=make_privacy(),
        occurred_at=datetime(2026, 3, 16, 12, 0, tzinfo=UTC),
        recorded_at=datetime(2026, 3, 16, 12, 0, tzinfo=UTC),
    )
    second = build_event(
        family_id=2,
        domain="task",
        event_type="task.completed",
        actor={"actor_type": "user", "actor_id": "viewer@example.com", "person_id": "person-viewer"},
        subject={"subject_type": "task", "subject_id": "502"},
        payload={"task_id": 502, "title": "Call electrician", "completed_by": "viewer@example.com"},
        source={"agent_id": "TaskAgent", "runtime": "backend", "session_id": "viewer-search"},
        privacy=make_privacy(),
        occurred_at=datetime(2026, 3, 16, 13, 0, tzinfo=UTC),
        recorded_at=datetime(2026, 3, 16, 13, 0, tzinfo=UTC),
    )
    first["source"]["agent_id"] = "TaskAgent"
    second["source"]["agent_id"] = "TaskAgent"
    for item in (first, second):
        ingest_family_event(db_session, item, subject="family.events.task")
    db_session.commit()

    _patch_viewer_dependencies(
        monkeypatch,
        me_payload={"authenticated": True, "email": "viewer@example.com", "memberships": []},
        context_payload=_viewer_context(family_id=2, person_id="person-viewer", is_family_admin=False, primary_email="viewer@example.com"),
        persons_payload=[_viewer_person(family_id=2, person_id="person-viewer", display_name="Viewer", email="viewer@example.com")],
    )

    response = client.get(
        "/v1/events/search?family_id=2&q=*electric*&limit=1&offset=0",
        headers={"X-Dev-User": "viewer@example.com"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["payload"]["title"] == "Call electrician"

    metadata_match = client.get(
        "/v1/events/search?family_id=2&q=*taskagent*",
        headers={"X-Dev-User": "viewer@example.com"},
    )
    assert metadata_match.status_code == 200
    assert metadata_match.json()["total"] == 2


def test_viewer_filter_options_follow_visible_scope(client, db_session, monkeypatch):
    own = build_event(
        family_id=2,
        domain="task",
        event_type="task.created",
        actor={"actor_type": "user", "actor_id": "viewer@example.com", "person_id": "person-viewer"},
        subject={"subject_type": "task", "subject_id": "501"},
        payload={"task_id": 501, "title": "Call plumber"},
        source={"agent_id": "TaskAgent", "runtime": "backend", "session_id": "viewer-options"},
        privacy=make_privacy(),
        tags=["household"],
        occurred_at=datetime(2026, 3, 16, 12, 0, tzinfo=UTC),
        recorded_at=datetime(2026, 3, 16, 12, 0, tzinfo=UTC),
    )
    targeted = build_event(
        family_id=2,
        domain="decision",
        event_type="decision.updated",
        actor={"actor_type": "user", "actor_id": "admin@example.com", "person_id": "person-admin"},
        subject={"subject_type": "decision", "subject_id": "777"},
        payload={"decision_id": 777, "title": "Camp plan", "target_person_id": "person-viewer"},
        source={"agent_id": "DecisionAgent", "runtime": "backend", "session_id": "viewer-options"},
        privacy=make_privacy(),
        tags=["planning"],
        occurred_at=datetime(2026, 3, 16, 13, 0, tzinfo=UTC),
        recorded_at=datetime(2026, 3, 16, 13, 0, tzinfo=UTC),
    )
    hidden = build_event(
        family_id=2,
        domain="note",
        event_type="note.created",
        actor={"actor_type": "user", "actor_id": "other@example.com", "person_id": "person-other"},
        subject={"subject_type": "note", "subject_id": "/Notes/private.md"},
        payload={"path": "/Notes/private.md", "title": "Private note"},
        source={"agent_id": "FileAgent", "runtime": "backend", "session_id": "viewer-options"},
        privacy=make_privacy(),
        tags=["private"],
        occurred_at=datetime(2026, 3, 16, 14, 0, tzinfo=UTC),
        recorded_at=datetime(2026, 3, 16, 14, 0, tzinfo=UTC),
    )
    for item, subject in (
        (own, "family.events.task"),
        (targeted, "family.events.decision"),
        (hidden, "family.events.note"),
    ):
        ingest_family_event(db_session, item, subject=subject)
    db_session.commit()

    _patch_viewer_dependencies(
        monkeypatch,
        me_payload={"authenticated": True, "email": "viewer@example.com", "memberships": []},
        context_payload=_viewer_context(family_id=2, person_id="person-viewer", is_family_admin=False, primary_email="viewer@example.com"),
        persons_payload=[
            _viewer_person(family_id=2, person_id="person-viewer", display_name="Viewer", email="viewer@example.com"),
            _viewer_person(family_id=2, person_id="person-admin", display_name="Admin", email="admin@example.com", is_admin=True),
            _viewer_person(family_id=2, person_id="person-other", display_name="Other", email="other@example.com"),
        ],
    )

    response = client.get("/v1/events/filter-options?family_id=2", headers={"X-Dev-User": "viewer@example.com"})
    assert response.status_code == 200
    body = response.json()
    assert body["domains"] == ["decision", "task"]
    assert body["event_types"] == ["decision.updated", "task.created"]
    assert body["tags"] == ["household", "planning"]
    assert body["actor_ids"] == ["admin@example.com", "viewer@example.com"]
    assert body["subject_ids"] == ["501", "777"]


def test_viewer_filter_options_support_admin_person_scope(client, db_session, monkeypatch):
    child_event = build_event(
        family_id=2,
        domain="task",
        event_type="task.created",
        actor={"actor_type": "user", "actor_id": "child@example.com"},
        subject={"subject_type": "task", "subject_id": "child-task"},
        payload={"task_id": 5, "title": "Kid chore"},
        source={"agent_id": "TaskAgent", "runtime": "backend", "session_id": "viewer-admin-options"},
        privacy=make_privacy(),
        tags=["chores"],
        occurred_at=datetime(2026, 3, 16, 12, 0, tzinfo=UTC),
        recorded_at=datetime(2026, 3, 16, 12, 0, tzinfo=UTC),
    )
    admin_event = build_event(
        family_id=2,
        domain="task",
        event_type="task.completed",
        actor={"actor_type": "user", "actor_id": "admin@example.com", "person_id": "person-admin"},
        subject={"subject_type": "task", "subject_id": "admin-task"},
        payload={"task_id": 6, "title": "Parent chore", "completed_by": "admin@example.com"},
        source={"agent_id": "TaskAgent", "runtime": "backend", "session_id": "viewer-admin-options"},
        privacy=make_privacy(),
        tags=["household"],
        occurred_at=datetime(2026, 3, 16, 13, 0, tzinfo=UTC),
        recorded_at=datetime(2026, 3, 16, 13, 0, tzinfo=UTC),
    )
    admin_event["actor"]["person_id"] = "person-admin"
    for item, subject in ((child_event, "family.events.task"), (admin_event, "family.events.task")):
        ingest_family_event(db_session, item, subject=subject)
    db_session.commit()

    _patch_viewer_dependencies(
        monkeypatch,
        me_payload={"authenticated": True, "email": "admin@example.com", "memberships": []},
        context_payload=_viewer_context(family_id=2, person_id="person-admin", is_family_admin=True, primary_email="admin@example.com"),
        persons_payload=[
            _viewer_person(family_id=2, person_id="person-admin", display_name="Admin", email="admin@example.com", is_admin=True),
            _viewer_person(family_id=2, person_id="person-child", display_name="Child", email="child@example.com"),
        ],
    )

    response = client.get(
        "/v1/events/filter-options?family_id=2&member_scope=person&person_id=person-child",
        headers={"X-Dev-User": "admin@example.com"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["domains"] == ["task"]
    assert body["event_types"] == ["task.created"]
    assert body["tags"] == ["chores"]
    assert body["actor_ids"] == ["child@example.com"]
    assert body["subject_ids"] == ["child-task"]


def test_viewer_filter_options_keep_same_field_relative_to_other_filters(client, db_session, monkeypatch):
    created = build_event(
        family_id=2,
        domain="task",
        event_type="task.created",
        actor={"actor_type": "user", "actor_id": "viewer@example.com", "person_id": "person-viewer"},
        subject={"subject_type": "task", "subject_id": "501"},
        payload={"task_id": 501, "title": "Call plumber"},
        source={"agent_id": "TaskAgent", "runtime": "backend", "session_id": "viewer-relative-options"},
        privacy=make_privacy(),
        tags=["household"],
        occurred_at=datetime(2026, 3, 16, 12, 0, tzinfo=UTC),
        recorded_at=datetime(2026, 3, 16, 12, 0, tzinfo=UTC),
    )
    completed = build_event(
        family_id=2,
        domain="task",
        event_type="task.completed",
        actor={"actor_type": "user", "actor_id": "viewer@example.com", "person_id": "person-viewer"},
        subject={"subject_type": "task", "subject_id": "502"},
        payload={"task_id": 502, "title": "Call electrician", "completed_by": "viewer@example.com"},
        source={"agent_id": "TaskAgent", "runtime": "backend", "session_id": "viewer-relative-options"},
        privacy=make_privacy(),
        tags=["household"],
        occurred_at=datetime(2026, 3, 16, 13, 0, tzinfo=UTC),
        recorded_at=datetime(2026, 3, 16, 13, 0, tzinfo=UTC),
    )
    note = build_event(
        family_id=2,
        domain="note",
        event_type="note.created",
        actor={"actor_type": "user", "actor_id": "viewer@example.com", "person_id": "person-viewer"},
        subject={"subject_type": "note", "subject_id": "/Notes/family.md"},
        payload={"path": "/Notes/family.md", "title": "Family note"},
        source={"agent_id": "FileAgent", "runtime": "backend", "session_id": "viewer-relative-options"},
        privacy=make_privacy(),
        tags=["reference"],
        occurred_at=datetime(2026, 3, 16, 14, 0, tzinfo=UTC),
        recorded_at=datetime(2026, 3, 16, 14, 0, tzinfo=UTC),
    )
    for item, subject in (
        (created, "family.events.task"),
        (completed, "family.events.task"),
        (note, "family.events.note"),
    ):
        ingest_family_event(db_session, item, subject=subject)
    db_session.commit()

    _patch_viewer_dependencies(
        monkeypatch,
        me_payload={"authenticated": True, "email": "viewer@example.com", "memberships": []},
        context_payload=_viewer_context(family_id=2, person_id="person-viewer", is_family_admin=False, primary_email="viewer@example.com"),
        persons_payload=[_viewer_person(family_id=2, person_id="person-viewer", display_name="Viewer", email="viewer@example.com")],
    )

    response = client.get(
        "/v1/events/filter-options?family_id=2&domain=task&event_type=task.created",
        headers={"X-Dev-User": "viewer@example.com"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["domains"] == ["task"]
    assert body["event_types"] == ["task.completed", "task.created"]
    assert body["tags"] == ["household"]
