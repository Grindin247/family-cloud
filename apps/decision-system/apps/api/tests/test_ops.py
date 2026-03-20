def _seed_family(client):
    family = client.post("/v1/families", json={"name": "Ops Family"})
    assert family.status_code == 201
    return family.json()["id"]


def test_agent_question_lifecycle_and_dedupe(client):
    family_id = _seed_family(client)

    payload = {
        "domain": "decision",
        "source_agent": "DecisionAgent",
        "topic": "Roadmap due soon",
        "summary": "A roadmap item is due soon.",
        "prompt": "Should this roadmap item be pushed out, completed, or removed?",
        "urgency": "high",
        "topic_type": "roadmap_due",
        "dedupe_key": "roadmap_due:1:2026-03-20",
        "context": {"roadmap_item_id": 1},
        "artifact_refs": [{"type": "roadmap_item", "id": 1}],
    }

    created = client.post(f"/v1/family/{family_id}/ops/questions", json=payload)
    assert created.status_code == 201
    created_body = created.json()
    question_id = created_body["question"]["id"]
    assert created_body["event"]["event_type"] == "created"

    updated = client.post(f"/v1/family/{family_id}/ops/questions", json={**payload, "summary": "Updated summary"})
    assert updated.status_code == 201
    updated_body = updated.json()
    assert updated_body["question"]["id"] == question_id
    assert updated_body["question"]["summary"] == "Updated summary"
    assert updated_body["event"]["event_type"] == "updated"

    asked = client.post(
        f"/v1/family/{family_id}/ops/questions/{question_id}/asked",
        json={"delivery_agent": "Caleb", "delivery_context": {"channel": "discord"}},
    )
    assert asked.status_code == 200
    assert asked.json()["question"]["status"] == "asked"

    resolved = client.post(
        f"/v1/family/{family_id}/ops/questions/{question_id}/resolve",
        json={"status": "resolved", "resolution_note": "User answered", "answer_sufficiency_state": "sufficient"},
    )
    assert resolved.status_code == 200
    assert resolved.json()["question"]["status"] == "resolved"

    active = client.get(f"/v1/family/{family_id}/ops/questions")
    assert active.status_code == 200
    assert active.json()["items"] == []

    history = client.get(f"/v1/family/{family_id}/ops/questions/history?question_id={question_id}")
    assert history.status_code == 200
    assert [item["event_type"] for item in history.json()] == ["resolved", "asked", "updated", "created"]


def test_metrics_and_playback_queries(client):
    family_id = _seed_family(client)

    event_payloads = [
        {
            "domain": "decision",
            "source_agent": "decision-api.decisions",
            "event_type": "decision_created",
            "summary": "Decision created",
            "topic": "Homeschool plan",
            "status": "Draft",
            "payload": {"decision_id": 10},
        },
        {
            "domain": "decision",
            "source_agent": "decision-api.decisions",
            "event_type": "decision_scored",
            "summary": "Decision scored",
            "topic": "Homeschool plan",
            "status": "Queued",
            "value_number": 4.5,
            "payload": {"decision_id": 10},
        },
        {
            "domain": "decision",
            "source_agent": "decision-api.decisions",
            "event_type": "goal_updated",
            "summary": "Goal updated",
            "topic": "Family Time",
            "status": "active",
            "payload": {"goal_id": 4},
        },
    ]

    for payload in event_payloads:
        response = client.post(f"/v1/family/{family_id}/ops/events", json=payload)
        assert response.status_code == 201

    metrics = client.post(
        f"/v1/family/{family_id}/ops/metrics/query",
        json={"domain": "decision", "metric_keys": ["decision_created_count", "decision_avg_score", "goal_updates_count"]},
    )
    assert metrics.status_code == 200
    items = {item["metric_key"]: item["value"] for item in metrics.json()["items"]}
    assert items["decision_created_count"] == 1.0
    assert items["decision_avg_score"] == 4.5
    assert items["goal_updates_count"] == 1.0

    playback = client.post(
        f"/v1/family/{family_id}/ops/playback/query",
        json={"domain": "decision", "event_types": ["decision_created", "decision_scored"], "limit": 10},
    )
    assert playback.status_code == 200
    event_types = [item["event_type"] for item in playback.json()["items"]]
    assert event_types == ["decision_scored", "decision_created"]


def test_task_metrics_and_admin_snapshot(client, monkeypatch):
    family_id = _seed_family(client)

    snapshot = {
        "overview": {
            "total_open_tasks": 9,
            "overdue_tasks": 2,
            "stale_tasks": 3,
        },
        "projects": [{"id": 1, "title": "Home"}],
        "member_load": [{"actor_id": "james", "open_tasks": 6, "overdue_tasks": 1, "due_soon_tasks": 2}],
        "project_load": [{"project_id": 1, "project_name": "Home", "open_tasks": 9, "overdue_tasks": 2, "stale_tasks": 3}],
        "findings": [{"type": "task_overdue", "summary": "Overdue task", "topic": "Overdue task: Paint", "artifact_refs": [], "context": {}, "dedupe_key": "task_overdue:1"}],
    }

    monkeypatch.setattr("app.services.ops.latest_task_health_snapshot", lambda: snapshot)
    monkeypatch.setattr("app.routers.ops.latest_task_health_snapshot", lambda: snapshot)

    for payload in [
        {
            "domain": "task",
            "source_agent": "TasksAgent",
            "event_type": "task_created",
            "summary": "Task created",
            "topic": "Paint fence",
            "payload": {"task_id": 1},
        },
        {
            "domain": "task",
            "source_agent": "TasksAgent",
            "event_type": "task_completed",
            "summary": "Task completed",
            "topic": "Buy groceries",
            "payload": {"task_id": 2},
        },
    ]:
        response = client.post(f"/v1/family/{family_id}/ops/events", json=payload)
        assert response.status_code == 201

    metrics = client.post(
        f"/v1/family/{family_id}/ops/metrics/query",
        json={"domain": "task", "metric_keys": ["task_created_count", "task_completion_count", "task_open_count", "project_count", "stale_task_count"]},
    )
    assert metrics.status_code == 200
    items = {item["metric_key"]: item for item in metrics.json()["items"]}
    assert items["task_created_count"]["value"] == 1.0
    assert items["task_completion_count"]["value"] == 1.0
    assert items["task_open_count"]["value"] == 9.0
    assert items["project_count"]["value"] == 1.0
    assert items["stale_task_count"]["value"] == 3.0

    snapshot_response = client.get(
        f"/v1/family/{family_id}/ops/admin/task-health-snapshot",
        headers={"X-Internal-Admin-Token": "change-me"},
    )
    assert snapshot_response.status_code == 200
    assert snapshot_response.json()["overview"]["total_open_tasks"] == 9


def test_ops_task_events_bridge_into_canonical_family_events(client):
    family_id = _seed_family(client)
    import app.services.ops as ops_service

    captured: list[dict] = []

    def _capture(event: dict):
        captured.append(event)
        return event["event_id"]

    ops_service._post_canonical_event = _capture

    created = client.post(
        f"/v1/family/{family_id}/ops/events",
        json={
            "domain": "task",
            "source_agent": "TasksAgent",
            "event_type": "task_created",
            "summary": "Task created",
            "topic": "Paint fence",
            "payload": {"task_id": 1, "title": "Paint fence", "tags": ["home"]},
        },
    )
    assert created.status_code == 201
    assert created.json()["canonical_event_id"]

    completed = client.post(
        f"/v1/family/{family_id}/ops/events",
        json={
            "domain": "task",
            "source_agent": "TasksAgent",
            "event_type": "task_completed",
            "summary": "Task completed",
            "topic": "Paint fence",
            "payload": {"task_id": 1, "title": "Paint fence"},
        },
    )
    assert completed.status_code == 201
    assert completed.json()["canonical_event_id"]
    assert [item["event_type"] for item in captured] == ["task.created", "task.completed"]


def test_ops_file_and_note_events_bridge_into_canonical_family_events(client):
    family_id = _seed_family(client)
    import app.services.ops as ops_service

    captured: list[dict] = []

    def _capture(event: dict):
        captured.append(event)
        return event["event_id"]

    ops_service._post_canonical_event = _capture

    file_response = client.post(
        f"/v1/family/{family_id}/ops/events",
        json={
            "domain": "file",
            "source_agent": "FileAgent",
            "event_type": "file_indexed",
            "summary": "Indexed file",
            "topic": "Contractor estimate",
            "payload": {
                "file_id": "file-1",
                "path": "/Notes/Inbox/contractor-estimate.md",
                "title": "Contractor estimate",
                "tags": ["home"],
            },
        },
    )
    assert file_response.status_code == 201
    assert file_response.json()["canonical_event_id"]

    note_response = client.post(
        f"/v1/family/{family_id}/ops/events",
        json={
            "domain": "note",
            "source_agent": "FileAgent",
            "event_type": "note_created",
            "summary": "Created note",
            "topic": "Sunday Service",
            "payload": {
                "path": "/Notes/Areas/Church/2026-03-16-sunday-service.md",
                "title": "Sunday Service",
                "note_type": "church",
                "tags": ["church"],
            },
        },
    )
    assert note_response.status_code == 201
    assert note_response.json()["canonical_event_id"]
    assert [item["event_type"] for item in captured] == ["file.indexed", "note.created"]
