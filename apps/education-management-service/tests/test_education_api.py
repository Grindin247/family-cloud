from __future__ import annotations

from uuid import uuid4


def _domain_id(client) -> str:
    response = client.get("/v1/domains?family_id=2", headers={"X-Dev-User": "admin@example.com"})
    assert response.status_code == 200
    return response.json()[0]["domain_id"]


def test_education_crud_and_summary_flow(client):
    learner_id = str(uuid4())
    domain_id = _domain_id(client)

    learner = client.post(
        "/v1/learners",
        headers={"X-Dev-User": "admin@example.com", "X-Idempotency-Key": "learner-1"},
        json={"family_id": 2, "learner_id": learner_id, "birthdate": "2015-05-01", "timezone": "America/New_York"},
    )
    assert learner.status_code == 201

    goal = client.post(
        "/v1/goals",
        headers={"X-Dev-User": "admin@example.com", "X-Idempotency-Key": "goal-1"},
        json={
            "family_id": 2,
            "learner_id": learner_id,
            "domain_id": domain_id,
            "title": "Master fractions",
            "description": "Get comfortable with adding fractions",
            "status": "active",
        },
    )
    assert goal.status_code == 201
    goal_id = goal.json()["goal_id"]

    goal_update = client.patch(
        f"/v1/goals/{goal_id}",
        headers={"X-Dev-User": "admin@example.com", "X-Idempotency-Key": "goal-update-1"},
        json={"status": "in_progress"},
    )
    assert goal_update.status_code == 200
    assert goal_update.json()["status"] == "in_progress"

    activity = client.post(
        "/v1/activities",
        headers={"X-Dev-User": "admin@example.com", "X-Idempotency-Key": "activity-1"},
        json={
            "family_id": 2,
            "learner_id": learner_id,
            "domain_id": domain_id,
            "activity_type": "lesson",
            "title": "Fraction lesson",
            "occurred_at": "2026-03-18T12:00:00Z",
            "duration_seconds": 1800,
            "source": "education-agent",
        },
    )
    assert activity.status_code == 201

    assignment = client.post(
        "/v1/assignments",
        headers={"X-Dev-User": "admin@example.com", "X-Idempotency-Key": "assignment-1"},
        json={
            "family_id": 2,
            "learner_id": learner_id,
            "domain_id": domain_id,
            "title": "Fraction worksheet",
            "status": "assigned",
            "source": "education-agent",
        },
    )
    assert assignment.status_code == 201
    assignment_id = assignment.json()["assignment_id"]

    assessment = client.post(
        "/v1/assessments",
        headers={"X-Dev-User": "admin@example.com", "X-Idempotency-Key": "assessment-1"},
        json={
            "family_id": 2,
            "learner_id": learner_id,
            "domain_id": domain_id,
            "assignment_id": assignment_id,
            "assessment_type": "graded_work",
            "title": "Fraction worksheet score",
            "occurred_at": "2026-03-18T12:30:00Z",
            "score": 8,
            "max_score": 10,
        },
    )
    assert assessment.status_code == 201

    practice = client.post(
        "/v1/practice-repetitions",
        headers={"X-Dev-User": "admin@example.com", "X-Idempotency-Key": "practice-1"},
        json={
            "family_id": 2,
            "learner_id": learner_id,
            "domain_id": domain_id,
            "occurred_at": "2026-03-18T13:00:00Z",
            "duration_seconds": 900,
            "performance_score": 0.8,
        },
    )
    assert practice.status_code == 201

    journal = client.post(
        "/v1/journals",
        headers={"X-Dev-User": "admin@example.com", "X-Idempotency-Key": "journal-1"},
        json={
            "family_id": 2,
            "learner_id": learner_id,
            "occurred_at": "2026-03-18T14:00:00Z",
            "title": "Fractions reflection",
            "content": "Fractions felt easier today.",
        },
    )
    assert journal.status_code == 201

    quiz = client.post(
        "/v1/quizzes",
        headers={"X-Dev-User": "admin@example.com", "X-Idempotency-Key": "quiz-1"},
        json={
            "family_id": 2,
            "learner_id": learner_id,
            "domain_id": domain_id,
            "title": "Fraction check-in",
            "delivery_mode": "chat",
            "source": "education-agent",
        },
    )
    assert quiz.status_code == 201
    quiz_id = quiz.json()["quiz_id"]

    quiz_items = client.post(
        f"/v1/quizzes/{quiz_id}/items",
        headers={"X-Dev-User": "admin@example.com", "X-Idempotency-Key": "quiz-items-1"},
        json={
            "family_id": 2,
            "items": [
                {"position": 1, "prompt_text": "What is 1/2 + 1/4?", "item_type": "short_answer", "max_score": 2},
                {"position": 2, "prompt_text": "Simplify 2/4", "item_type": "short_answer", "max_score": 1},
            ],
        },
    )
    assert quiz_items.status_code == 201

    quiz_responses = client.post(
        f"/v1/quizzes/{quiz_id}/responses",
        headers={"X-Dev-User": "admin@example.com", "X-Idempotency-Key": "quiz-responses-1"},
        json={
            "family_id": 2,
            "learner_id": learner_id,
            "responses": [
                {"quiz_item_id": quiz_items.json()[0]["quiz_item_id"], "response_json": "3/4", "score": 2, "max_score": 2, "correctness": True},
                {"quiz_item_id": quiz_items.json()[1]["quiz_item_id"], "response_json": "1/2", "score": 1, "max_score": 1, "correctness": True},
            ],
        },
    )
    assert quiz_responses.status_code == 201

    stats = client.get(f"/v1/learners/{learner_id}/stats?family_id=2", headers={"X-Dev-User": "admin@example.com"})
    assert stats.status_code == 200
    assert stats.json()["activity_count_30d"] == 1
    assert stats.json()["assessment_count_30d"] == 1

    snapshots = client.get(
        f"/v1/learners/{learner_id}/progress-snapshots?family_id=2",
        headers={"X-Dev-User": "admin@example.com"},
    )
    assert snapshots.status_code == 200
    assert snapshots.json()

    summary = client.get(
        f"/v1/learners/{learner_id}/education-summary?family_id=2",
        headers={"X-Dev-User": "admin@example.com"},
    )
    assert summary.status_code == 200
    body = summary.json()
    assert body["learner"]["learner_id"] == learner_id
    assert body["recent_assessments"][0]["title"] == "Fraction worksheet score"
    assert body["recent_quiz_sessions"][0]["quiz_id"] == quiz_id


def test_idempotent_retry_returns_same_response(client):
    learner_id = str(uuid4())
    response_one = client.post(
        "/v1/learners",
        headers={"X-Dev-User": "admin@example.com", "X-Idempotency-Key": "same-learner"},
        json={"family_id": 2, "learner_id": learner_id, "timezone": "UTC"},
    )
    assert response_one.status_code == 201

    response_two = client.post(
        "/v1/learners",
        headers={"X-Dev-User": "admin@example.com", "X-Idempotency-Key": "same-learner"},
        json={"family_id": 2, "learner_id": learner_id, "timezone": "UTC"},
    )
    assert response_two.status_code == 201
    assert response_two.json() == response_one.json()


def test_idempotency_conflict_returns_409(client):
    learner_id = str(uuid4())
    response_one = client.post(
        "/v1/learners",
        headers={"X-Dev-User": "admin@example.com", "X-Idempotency-Key": "conflict-learner"},
        json={"family_id": 2, "learner_id": learner_id, "timezone": "UTC"},
    )
    assert response_one.status_code == 201

    response_two = client.post(
        "/v1/learners",
        headers={"X-Dev-User": "admin@example.com", "X-Idempotency-Key": "conflict-learner"},
        json={"family_id": 2, "learner_id": learner_id, "timezone": "America/New_York"},
    )
    assert response_two.status_code == 409
    assert response_two.json()["detail"]["code"] == "idempotency_conflict"
