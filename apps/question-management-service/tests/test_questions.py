from datetime import UTC, datetime


def _headers() -> dict[str, str]:
    return {"X-Dev-User": "admin@example.com"}


def test_question_lifecycle_and_claiming(client, reset_db):
    created = client.post(
        "/v1/families/2/questions",
        headers=_headers(),
        json={
            "domain": "task",
            "source_agent": "TasksAgent",
            "topic": "Overdue task: Call plumber",
            "summary": "Call plumber is overdue.",
            "prompt": "Can you still handle the plumber call today?",
            "urgency": "high",
            "category": "task_overdue",
            "dedupe_key": "task_overdue:12",
            "context": {"task_id": 12, "project_id": 4},
            "artifact_refs": [{"type": "task", "id": 12}],
        },
    )
    assert created.status_code == 201
    question = created.json()["question"]
    assert question["category"] == "task_overdue"

    claim = client.post(
        "/v1/families/2/questions/claim-next",
        headers=_headers(),
        json={"agent_id": "Caleb", "channel": "discord_dm", "force": True},
    )
    assert claim.status_code == 200
    payload = claim.json()
    assert payload["eligible"] is True
    assert len(payload["items"]) == 1
    claim_token = payload["claim_token"]
    question_id = payload["items"][0]["id"]

    asked = client.post(
        f"/v1/families/2/questions/{question_id}/asked",
        headers=_headers(),
        json={"delivery_agent": "Caleb", "delivery_channel": "discord_dm", "claim_token": claim_token},
    )
    assert asked.status_code == 200
    assert asked.json()["question"]["status"] == "asked"
    assert asked.json()["attempt"]["channel"] == "discord_dm"

    answer = client.post(
        f"/v1/families/2/questions/{question_id}/answer",
        headers=_headers(),
        json={"answer_text": "Yes, I can handle it this afternoon."},
    )
    assert answer.status_code == 200
    assert answer.json()["question"]["status"] == "resolved"
    assert answer.json()["attempt"]["outcome"] == "responded"

    history = client.get(f"/v1/families/2/questions/history?question_id={question_id}", headers=_headers())
    assert history.status_code == 200
    assert any(event["event_type"] == "asked" for event in history.json()["events"])
    assert any(attempt["responded_at"] is not None for attempt in history.json()["attempts"])

    canonical_types = [event["event_type"] for event in reset_db["published_events"]]
    assert canonical_types == [
        "question.created",
        "question.claimed",
        "question.asked",
        "question.answered",
    ]
    created_event = reset_db["published_events"][0]
    assert created_event["payload"]["prompt_snippet"] == "Can you still handle the plumber call today?"
    assert "prompt" not in created_event["payload"]
    assert created_event["privacy"]["contains_free_text"] is True
    answered_event = reset_db["published_events"][-1]
    assert answered_event["payload"]["answer_text_snippet"] == "Yes, I can handle it this afternoon."
    assert answered_event["payload"]["delivery"]["outcome"] == "responded"


def test_question_noise_is_suppressed(client, reset_db):
    created = client.post(
        "/v1/families/2/questions",
        headers=_headers(),
        json={
            "domain": "task",
            "source_agent": "TasksAgent",
            "topic": "Smoke test task",
            "summary": "This is a smoke test placeholder.",
            "prompt": "Ignore me.",
            "urgency": "medium",
            "category": "task_overdue",
            "dedupe_key": "noise:1",
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["suppressed"] is True
    listed = client.get("/v1/families/2/questions", headers=_headers())
    assert listed.status_code == 200
    assert listed.json()["items"] == []
    assert reset_db["published_events"] == []


def test_question_update_emits_changed_fields(client, reset_db):
    created = client.post(
        "/v1/families/2/questions",
        headers=_headers(),
        json={
            "domain": "planning",
            "source_agent": "PlanningAgent",
            "topic": "Missing timezone",
            "summary": "Need a timezone for the new plan.",
            "prompt": "Which timezone should this plan use?",
            "urgency": "medium",
            "category": "plan_missing_field",
            "dedupe_key": "plan:1:schedule.timezone",
            "context": {"plan_id": "plan-1"},
        },
    )
    assert created.status_code == 201
    question_id = created.json()["question"]["id"]

    updated = client.patch(
        f"/v1/families/2/questions/{question_id}",
        headers=_headers(),
        json={
            "summary": "Need a timezone before activation.",
            "prompt": "Which timezone should we use before turning the plan on?",
            "urgency": "high",
            "context_patch": {"owner_person_id": "00000000-0000-0000-0000-000000000010"},
        },
    )
    assert updated.status_code == 200

    canonical_event = reset_db["published_events"][-1]
    assert canonical_event["event_type"] == "question.updated"
    assert set(canonical_event["payload"]["changed_fields"]) >= {"summary", "prompt", "urgency", "context.owner_person_id"}
    assert canonical_event["payload"]["prompt_snippet"] == "Which timezone should we use before turning the plan on?"


def test_claim_next_questions_respects_quiet_hours_and_leaves_items_queued(client, monkeypatch, reset_db):
    created = client.post(
        "/v1/families/2/questions",
        headers=_headers(),
        json={
            "domain": "planning",
            "source_agent": "PlanningAgent",
            "topic": "Missing timezone",
            "summary": "Need a timezone before the overnight brief can recommend activation.",
            "prompt": "Which timezone should we use for this plan?",
            "urgency": "medium",
            "category": "plan_missing_field",
            "dedupe_key": "plan:overnight:schedule.timezone",
        },
    )
    assert created.status_code == 201
    question_id = created.json()["question"]["id"]

    monkeypatch.setattr(
        "app.services.questions._utcnow",
        lambda: datetime(2026, 3, 25, 3, 15, tzinfo=UTC),
    )

    claim = client.post(
        "/v1/families/2/questions/claim-next",
        headers=_headers(),
        json={"agent_id": "Caleb", "channel": "discord_dm"},
    )
    assert claim.status_code == 200
    assert claim.json()["eligible"] is False
    assert claim.json()["reason"] == "quiet_hours"
    assert claim.json()["items"] == []

    listed = client.get("/v1/families/2/questions", headers=_headers())
    assert listed.status_code == 200
    question = next(item for item in listed.json()["items"] if item["id"] == question_id)
    assert question["status"] == "pending"

    event_types = [event["event_type"] for event in reset_db["published_events"]]
    assert event_types == ["question.created"]


def test_purge_questions(client, reset_db):
    for index in range(2):
        response = client.post(
            "/v1/families/2/questions",
            headers=_headers(),
            json={
                "domain": "education",
                "source_agent": "EducationAgent",
                "topic": f"Education question {index}",
                "summary": "Needs follow-up.",
                "prompt": "Can you help?",
                "urgency": "medium",
                "category": "practice_gap",
                "dedupe_key": f"education:{index}",
            },
        )
        assert response.status_code == 201

    purge = client.post(
        "/v1/families/2/questions/purge",
        headers=_headers(),
        json={"domain": "education"},
    )
    assert purge.status_code == 200
    assert purge.json()["deleted"] == 2
    canonical_event = reset_db["published_events"][-1]
    assert canonical_event["event_type"] == "question.purged"
    assert canonical_event["payload"]["purged_count"] == 2
    assert canonical_event["source"]["channel"] is None
