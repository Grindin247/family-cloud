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

    quizzes = client.get(
        f"/v1/learners/{learner_id}/quizzes?family_id=2",
        headers={"X-Dev-User": "admin@example.com"},
    )
    assert quizzes.status_code == 200
    assert quizzes.json()[0]["quiz_id"] == quiz_id


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


def test_viewer_context_feature_toggle_and_dashboard(client, monkeypatch):
    feature_state = {"enabled": False}

    monkeypatch.setattr(
        "app.routers.education.get_family_features",
        lambda **kwargs: [
            {
                "family_id": kwargs["family_id"],
                "feature_key": "education",
                "enabled": feature_state["enabled"],
                "config": {},
                "updated_at": "2026-03-21T12:00:00Z",
            }
        ],
    )
    monkeypatch.setattr(
        "app.routers.education.update_family_feature",
        lambda **kwargs: {
            "family_id": kwargs["family_id"],
            "feature_key": kwargs["feature_key"],
            "enabled": feature_state.__setitem__("enabled", kwargs["enabled"]) or feature_state["enabled"],
            "config": kwargs["config"],
            "updated_at": "2026-03-21T12:00:00Z",
        },
    )

    learner_id = "00000000-0000-0000-0000-000000000011"
    domain_id = _domain_id(client)

    me = client.get("/v1/me", headers={"X-Dev-User": "admin@example.com"})
    assert me.status_code == 200
    assert me.json()["memberships"][0]["family_id"] == 2

    context = client.get("/v1/families/2/viewer-context", headers={"X-Dev-User": "admin@example.com"})
    assert context.status_code == 200
    assert context.json()["education_enabled"] is False

    toggle = client.put(
        "/v1/families/2/education-feature",
        headers={"X-Dev-User": "admin@example.com"},
        json={"enabled": True, "config": {"mode": "dashboard"}},
    )
    assert toggle.status_code == 200
    assert toggle.json()["enabled"] is True

    context_after = client.get("/v1/families/2/viewer-context", headers={"X-Dev-User": "admin@example.com"})
    assert context_after.status_code == 200
    assert context_after.json()["education_enabled"] is True

    learner = client.post(
        "/v1/learners",
        headers={"X-Dev-User": "admin@example.com", "X-Idempotency-Key": "dashboard-learner"},
        json={"family_id": 2, "learner_id": learner_id, "timezone": "America/New_York"},
    )
    assert learner.status_code == 201

    goal = client.post(
        "/v1/goals",
        headers={"X-Dev-User": "admin@example.com", "X-Idempotency-Key": "dashboard-goal"},
        json={
            "family_id": 2,
            "learner_id": learner_id,
            "domain_id": domain_id,
            "title": "Reading goal",
            "status": "active",
        },
    )
    assert goal.status_code == 201

    activity = client.post(
        "/v1/activities",
        headers={"X-Dev-User": "admin@example.com", "X-Idempotency-Key": "dashboard-activity"},
        json={
            "family_id": 2,
            "learner_id": learner_id,
            "domain_id": domain_id,
            "activity_type": "lesson",
            "title": "Reading session",
            "occurred_at": "2026-03-20T12:00:00Z",
            "duration_seconds": 1200,
        },
    )
    assert activity.status_code == 201

    assignment = client.post(
        "/v1/assignments",
        headers={"X-Dev-User": "admin@example.com", "X-Idempotency-Key": "dashboard-assignment"},
        json={
            "family_id": 2,
            "learner_id": learner_id,
            "domain_id": domain_id,
            "title": "Reading worksheet",
            "status": "assigned",
            "due_at": "2026-03-22T12:00:00Z",
            "source": "education-agent",
        },
    )
    assert assignment.status_code == 201

    assessment = client.post(
        "/v1/assessments",
        headers={"X-Dev-User": "admin@example.com", "X-Idempotency-Key": "dashboard-assessment"},
        json={
            "family_id": 2,
            "learner_id": learner_id,
            "domain_id": domain_id,
            "assessment_type": "graded_work",
            "title": "Reading check",
            "occurred_at": "2026-03-20T12:30:00Z",
            "score": 9,
            "max_score": 10,
        },
    )
    assert assessment.status_code == 201

    practice = client.post(
        "/v1/practice-repetitions",
        headers={"X-Dev-User": "admin@example.com", "X-Idempotency-Key": "dashboard-practice"},
        json={
            "family_id": 2,
            "learner_id": learner_id,
            "domain_id": domain_id,
            "occurred_at": "2026-03-20T13:00:00Z",
            "duration_seconds": 600,
            "performance_score": 0.9,
        },
    )
    assert practice.status_code == 201

    dashboard = client.get("/v1/families/2/dashboard", headers={"X-Dev-User": "admin@example.com"})
    assert dashboard.status_code == 200
    body = dashboard.json()
    assert body["kpis"]["tracked_learner_count"] == 1
    assert body["kpis"]["untracked_person_count"] == 1
    assert body["kpis"]["active_goal_count"] == 1
    assert body["kpis"]["open_assignment_count"] == 1
    assert body["tracked_learners"][0]["learner"]["learner_id"] == learner_id
    assert body["tracked_learners"][0]["current_focus_text"] == "Reading worksheet"
    assert body["tracked_learners"][0]["score_trend_points"]


def test_patch_routes_refresh_snapshots_and_list_quizzes(client):
    learner_id = str(uuid4())
    domain_id = _domain_id(client)

    learner = client.post(
        "/v1/learners",
        headers={"X-Dev-User": "admin@example.com", "X-Idempotency-Key": "patch-learner"},
        json={"family_id": 2, "learner_id": learner_id, "timezone": "UTC"},
    )
    assert learner.status_code == 201

    activity = client.post(
        "/v1/activities",
        headers={"X-Dev-User": "admin@example.com", "X-Idempotency-Key": "patch-activity"},
        json={
            "family_id": 2,
            "learner_id": learner_id,
            "domain_id": domain_id,
            "activity_type": "lesson",
            "title": "Original lesson",
            "occurred_at": "2026-03-18T12:00:00Z",
            "duration_seconds": 900,
        },
    )
    assert activity.status_code == 201
    activity_id = activity.json()["activity_id"]

    assignment = client.post(
        "/v1/assignments",
        headers={"X-Dev-User": "admin@example.com", "X-Idempotency-Key": "patch-assignment"},
        json={
            "family_id": 2,
            "learner_id": learner_id,
            "domain_id": domain_id,
            "title": "Original assignment",
            "status": "assigned",
            "source": "education-agent",
        },
    )
    assert assignment.status_code == 201
    assignment_id = assignment.json()["assignment_id"]

    assessment = client.post(
        "/v1/assessments",
        headers={"X-Dev-User": "admin@example.com", "X-Idempotency-Key": "patch-assessment"},
        json={
            "family_id": 2,
            "learner_id": learner_id,
            "domain_id": domain_id,
            "assignment_id": assignment_id,
            "assessment_type": "graded_work",
            "title": "Original assessment",
            "occurred_at": "2026-03-18T12:30:00Z",
            "score": 8,
            "max_score": 10,
        },
    )
    assert assessment.status_code == 201
    assessment_id = assessment.json()["assessment_id"]

    practice = client.post(
        "/v1/practice-repetitions",
        headers={"X-Dev-User": "admin@example.com", "X-Idempotency-Key": "patch-practice"},
        json={
            "family_id": 2,
            "learner_id": learner_id,
            "domain_id": domain_id,
            "occurred_at": "2026-03-18T13:00:00Z",
            "duration_seconds": 600,
            "performance_score": 0.8,
        },
    )
    assert practice.status_code == 201
    repetition_id = practice.json()["repetition_id"]

    journal = client.post(
        "/v1/journals",
        headers={"X-Dev-User": "admin@example.com", "X-Idempotency-Key": "patch-journal"},
        json={
            "family_id": 2,
            "learner_id": learner_id,
            "occurred_at": "2026-03-18T14:00:00Z",
            "title": "Original journal",
            "content": "Original content",
        },
    )
    assert journal.status_code == 201
    journal_id = journal.json()["journal_id"]

    quiz = client.post(
        "/v1/quizzes",
        headers={"X-Dev-User": "admin@example.com", "X-Idempotency-Key": "patch-quiz"},
        json={
            "family_id": 2,
            "learner_id": learner_id,
            "domain_id": domain_id,
            "title": "Quiz one",
            "delivery_mode": "chat",
            "source": "education-agent",
        },
    )
    assert quiz.status_code == 201
    quiz_id = quiz.json()["quiz_id"]

    learner_patch = client.patch(
        f"/v1/learners/{learner_id}",
        headers={"X-Dev-User": "admin@example.com", "X-Idempotency-Key": "patch-learner-update"},
        json={"display_name": "Updated learner", "timezone": "America/New_York", "status": "paused"},
    )
    assert learner_patch.status_code == 200
    assert learner_patch.json()["display_name"] == "Updated learner"

    activity_patch = client.patch(
        f"/v1/activities/{activity_id}",
        headers={"X-Dev-User": "admin@example.com", "X-Idempotency-Key": "patch-activity-update"},
        json={"title": "Updated lesson", "duration_seconds": 1800},
    )
    assert activity_patch.status_code == 200
    assert activity_patch.json()["title"] == "Updated lesson"

    assignment_patch = client.patch(
        f"/v1/assignments/{assignment_id}",
        headers={"X-Dev-User": "admin@example.com", "X-Idempotency-Key": "patch-assignment-update"},
        json={"status": "completed"},
    )
    assert assignment_patch.status_code == 200
    assert assignment_patch.json()["status"] == "completed"

    assessment_patch = client.patch(
        f"/v1/assessments/{assessment_id}",
        headers={"X-Dev-User": "admin@example.com", "X-Idempotency-Key": "patch-assessment-update"},
        json={"score": 10, "max_score": 20, "title": "Updated assessment"},
    )
    assert assessment_patch.status_code == 200
    assert assessment_patch.json()["title"] == "Updated assessment"

    practice_patch = client.patch(
        f"/v1/practice-repetitions/{repetition_id}",
        headers={"X-Dev-User": "admin@example.com", "X-Idempotency-Key": "patch-practice-update"},
        json={"topic_text": "Updated topic", "performance_score": 0.95},
    )
    assert practice_patch.status_code == 200
    assert practice_patch.json()["topic_text"] == "Updated topic"

    journal_patch = client.patch(
        f"/v1/journals/{journal_id}",
        headers={"X-Dev-User": "admin@example.com", "X-Idempotency-Key": "patch-journal-update"},
        json={"title": "Updated journal", "content": "Updated content"},
    )
    assert journal_patch.status_code == 200
    assert journal_patch.json()["title"] == "Updated journal"

    snapshots = client.get(
        f"/v1/learners/{learner_id}/progress-snapshots?family_id=2",
        headers={"X-Dev-User": "admin@example.com"},
    )
    assert snapshots.status_code == 200
    assert snapshots.json()[0]["latest_score"] == 50.0

    quizzes = client.get(
        f"/v1/learners/{learner_id}/quizzes?family_id=2",
        headers={"X-Dev-User": "admin@example.com"},
    )
    assert quizzes.status_code == 200
    assert quizzes.json()[0]["quiz_id"] == quiz_id
