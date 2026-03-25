from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.models.planning import PlanInstance


def _headers():
    return {"X-Dev-User": "admin@example.com"}


def test_viewer_context_feature_toggle_and_goal_options(client):
    me = client.get("/v1/me", headers=_headers())
    assert me.status_code == 200
    assert me.json()["email"] == "admin@example.com"

    context = client.get("/v1/families/2/viewer-context", headers=_headers())
    assert context.status_code == 200
    assert context.json()["planning_enabled"] is True

    toggled = client.put("/v1/families/2/planning-feature", json={"enabled": True, "config": {}}, headers=_headers())
    assert toggled.status_code == 200
    assert toggled.json()["feature_key"] == "planning"

    goals = client.get("/v1/families/2/plans/goal-options", headers=_headers())
    assert goals.status_code == 200
    assert goals.json()["items"][0]["goal_id"] == 11


def test_draft_plan_queues_missing_questions_and_preserves_task_suggestions(client, reset_db):
    response = client.post(
        "/v1/families/2/plans",
        headers=_headers(),
        json={
            "title": "Weeknight dinner plan",
            "plan_kind": "meal_plan",
            "status": "draft",
            "owner_scope": "family",
            "participant_person_ids": ["00000000-0000-0000-0000-000000000010", "00000000-0000-0000-0000-000000000011"],
            "schedule": {"frequency": "weekly", "weekdays": ["monday", "wednesday", "friday"]},
            "goal_links": [{"goal_id": 11, "goal_scope": "family", "weight": 0.8, "rationale": "Dinner cadence"}],
            "task_suggestions": [{"title": "Order groceries", "summary": "Prep ingredients", "status": "suggested"}],
            "feasibility_summary": {"status": "watch", "notes": ["Need timezone to finalize schedule."]},
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert "schedule.timezone" in body["missing_fields"]
    assert body["task_suggestions"][0]["external_task_ref"] is None
    assert body["alignment_summary"]["linked_goal_count"] == 1

    queued = reset_db["queued_questions"]
    assert len(queued) == 1
    payload = queued[0]["payload"]
    assert payload["domain"] == "planning"
    assert payload["source_agent"] == "planning-agent"
    assert payload["dedupe_key"].endswith(":schedule.timezone")

    preview = client.get(f"/v1/families/2/plans/{body['plan_id']}/preview?days=7", headers=_headers())
    assert preview.status_code == 200
    assert preview.json()["task_suggestions"][0]["title"] == "Order groceries"

    created_event = reset_db["published_events"][0]
    assert created_event["event_type"] == "plan.created"
    assert created_event["payload"]["title_snippet"] == "Weeknight dinner plan"
    assert created_event["payload"]["participant_count"] == 2
    assert created_event["payload"]["goal_count"] == 1
    assert created_event["payload"]["schedule_summary"]["frequency"] == "weekly"


def test_overnight_safe_plan_updates_do_not_change_status_and_keep_missing_questions_queued(client, reset_db):
    created = client.post(
        "/v1/families/2/plans",
        headers=_headers(),
        json={
            "title": "Bench press progression",
            "plan_kind": "fitness_plan",
            "status": "draft",
            "owner_scope": "person",
            "owner_person_id": "00000000-0000-0000-0000-000000000010",
            "participant_person_ids": ["00000000-0000-0000-0000-000000000010"],
            "schedule": {"frequency": "weekly", "weekdays": ["monday", "thursday"]},
            "task_suggestions": [{"title": "Track protein", "summary": "Aim for a consistent recovery target", "status": "suggested"}],
            "feasibility_summary": {"status": "watch", "notes": ["Need timezone before activation."]},
        },
    )
    assert created.status_code == 201
    body = created.json()
    plan_id = body["plan_id"]
    assert body["status"] == "draft"
    assert "schedule.timezone" in body["missing_fields"]

    updated = client.put(
        f"/v1/families/2/plans/{plan_id}",
        headers=_headers(),
        json={
            "task_suggestions": [
                {"title": "Prep bench day breakfast", "summary": "Add carbs and protein before the morning lift", "status": "suggested"}
            ],
            "feasibility_summary": {"status": "watch", "notes": ["Still waiting on timezone before activation."]},
        },
    )
    assert updated.status_code == 200
    refreshed = updated.json()
    assert refreshed["status"] == "draft"
    assert refreshed["task_suggestions"][0]["title"] == "Prep bench day breakfast"
    assert refreshed["feasibility_summary"]["status"] == "watch"
    assert "schedule.timezone" in refreshed["missing_fields"]

    queued = reset_db["queued_questions"]
    assert len(queued) >= 2
    assert queued[-1]["payload"]["domain"] == "planning"
    assert queued[-1]["payload"]["source_agent"] == "planning-agent"
    assert queued[-1]["payload"]["dedupe_key"].endswith(":schedule.timezone")

    updated_event = next(event for event in reset_db["published_events"] if event["event_type"] == "plan.updated")
    assert "status" not in updated_event["payload"]["changed_fields"]


def test_individual_plan_activation_instances_and_checkins(client, reset_db):
    created = client.post(
        "/v1/families/2/plans",
        headers=_headers(),
        json={
            "title": "Beginner strength block",
            "summary": "Three day intro strength plan.",
            "plan_kind": "fitness_plan",
            "status": "draft",
            "owner_scope": "person",
            "owner_person_id": "00000000-0000-0000-0000-000000000010",
            "participant_person_ids": ["00000000-0000-0000-0000-000000000010"],
            "schedule": {
                "timezone": "America/New_York",
                "frequency": "weekly",
                "weekdays": ["monday", "wednesday", "friday"],
                "local_time": "07:15:00",
            },
            "goal_links": [{"goal_id": 12, "goal_scope": "person", "weight": 0.9, "rationale": "Supports strength goal"}],
            "task_suggestions": [{"title": "Buy yoga mat", "summary": "Optional support gear", "status": "suggested"}],
            "feasibility_summary": {"status": "ready", "notes": ["Dumbbells only."]},
        },
    )
    assert created.status_code == 201
    plan_id = created.json()["plan_id"]

    activated = client.post(f"/v1/families/2/plans/{plan_id}/activate", headers=_headers())
    assert activated.status_code == 200
    assert activated.json()["status"] == "active"

    instances = client.get(f"/v1/families/2/plans/{plan_id}/instances", headers=_headers())
    assert instances.status_code == 200
    assert len(instances.json()["items"]) >= 1
    first_instance = instances.json()["items"][0]

    checked = client.post(
        f"/v1/families/2/plans/{plan_id}/checkins",
        headers=_headers(),
        json={
            "plan_instance_id": first_instance["instance_id"],
            "status": "done",
            "note": "Finished the first session.",
            "rating": 4,
            "blockers": ["left knee felt tight"],
            "confidence": "medium",
            "qualitative_update": "Need lighter squats next time.",
        },
    )
    assert checked.status_code == 200
    detail = checked.json()
    assert detail["adherence_summary"]["completed_count"] == 1
    assert detail["task_suggestions"][0]["status"] == "suggested"

    event_types = [event["event_type"] for event in reset_db["published_events"]]
    assert "plan.created" in event_types
    assert "plan.activated" in event_types
    assert "plan.instance.completed" in event_types
    assert "plan.checkin.recorded" in event_types
    completed_event = next(event for event in reset_db["published_events"] if event["event_type"] == "plan.instance.completed")
    checkin_event = next(event for event in reset_db["published_events"] if event["event_type"] == "plan.checkin.recorded")
    assert completed_event["correlation"]["correlation_id"] == checkin_event["correlation"]["correlation_id"]
    assert checkin_event["payload"]["checkin_note_snippet"] == "Finished the first session."
    assert checkin_event["payload"]["qualitative_update_snippet"] == "Need lighter squats next time."


def test_overnight_plan_updates_can_refresh_safe_fields_without_pausing_or_archiving_active_plans(client, reset_db):
    created = client.post(
        "/v1/families/2/plans",
        headers=_headers(),
        json={
            "title": "Strength block",
            "plan_kind": "fitness_plan",
            "status": "draft",
            "owner_scope": "person",
            "owner_person_id": "00000000-0000-0000-0000-000000000010",
            "participant_person_ids": ["00000000-0000-0000-0000-000000000010"],
            "schedule": {
                "timezone": "America/New_York",
                "frequency": "weekly",
                "weekdays": ["monday", "wednesday", "friday"],
                "local_time": "07:00:00",
            },
            "task_suggestions": [{"title": "Buy wrist wraps", "summary": "Optional bench support", "status": "suggested"}],
            "feasibility_summary": {"status": "ready", "notes": ["Garage setup is enough."]},
        },
    )
    assert created.status_code == 201
    plan_id = created.json()["plan_id"]

    activated = client.post(f"/v1/families/2/plans/{plan_id}/activate", headers=_headers())
    assert activated.status_code == 200
    assert activated.json()["status"] == "active"

    updated = client.put(
        f"/v1/families/2/plans/{plan_id}",
        headers=_headers(),
        json={
            "task_suggestions": [{"title": "Pack post-workout shake", "summary": "Reduce missed recovery meals", "status": "suggested"}],
            "feasibility_summary": {"status": "ready", "notes": ["Recovery meals are now prepped ahead."]},
        },
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["status"] == "active"
    assert body["task_suggestions"][0]["title"] == "Pack post-workout shake"
    assert body["feasibility_summary"]["notes"] == ["Recovery meals are now prepped ahead."]


def test_invalid_goal_and_participant_validation(client):
    participant_error = client.post(
        "/v1/families/2/plans",
        headers=_headers(),
        json={
            "title": "Invalid participants",
            "plan_kind": "routine",
            "status": "draft",
            "owner_scope": "family",
            "participant_person_ids": ["00000000-0000-0000-0000-000000009999"],
            "schedule": {"frequency": "daily", "timezone": "UTC"},
        },
    )
    assert participant_error.status_code == 404
    assert participant_error.json()["detail"]["code"] == "person_not_found"

    goal_error = client.post(
        "/v1/families/2/plans",
        headers=_headers(),
        json={
            "title": "Bad goal",
            "plan_kind": "habit",
            "status": "draft",
            "owner_scope": "family",
            "participant_person_ids": ["00000000-0000-0000-0000-000000000010"],
            "schedule": {"frequency": "daily", "timezone": "UTC"},
            "goal_links": [{"goal_id": 999, "goal_scope": "family", "weight": 0.4}],
        },
    )
    assert goal_error.status_code == 404
    assert goal_error.json()["detail"]["code"] == "goal_not_found"


def test_reconcile_marks_past_instances_missed(client, db_session):
    created = client.post(
        "/v1/families/2/plans",
        headers=_headers(),
        json={
            "title": "Study cadence",
            "plan_kind": "study_plan",
            "status": "draft",
            "owner_scope": "person",
            "owner_person_id": "00000000-0000-0000-0000-000000000011",
            "participant_person_ids": ["00000000-0000-0000-0000-000000000011"],
            "schedule": {"timezone": "UTC", "frequency": "daily"},
        },
    )
    assert created.status_code == 201
    plan_id = created.json()["plan_id"]
    activated = client.post(f"/v1/families/2/plans/{plan_id}/activate", headers=_headers())
    assert activated.status_code == 200

    instance = db_session.query(PlanInstance).filter(PlanInstance.plan_id == UUID(plan_id)).order_by(PlanInstance.scheduled_for.asc()).first()
    assert instance is not None
    instance.scheduled_for = datetime.now(UTC) - timedelta(days=1)
    instance.status = "scheduled"
    db_session.commit()

    detail = client.get(f"/v1/families/2/plans/{plan_id}", headers=_headers())
    assert detail.status_code == 200
    refreshed = client.get(f"/v1/families/2/plans/{plan_id}/instances", headers=_headers())
    assert refreshed.status_code == 200
    assert refreshed.json()["items"][0]["status"] == "missed"
