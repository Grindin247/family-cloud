def _headers() -> dict[str, str]:
    return {"X-Dev-User": "admin@example.com"}


def test_question_lifecycle_and_claiming(client):
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


def test_question_noise_is_suppressed(client):
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


def test_purge_questions(client):
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
