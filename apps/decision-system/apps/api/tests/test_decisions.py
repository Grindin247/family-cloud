from app.models.entities import (
    Decision,
    DecisionStatusEnum,
    DecisionQueueItem,
    DecisionScoreRun,
)


def _person_map(client, family_id):
    persons = client.get(f"/v1/families/{family_id}/persons").json()["items"]
    return {item["legacy_member_id"]: item for item in persons}


def _seed_family_context(client):
    family_response = client.post("/v1/families", json={"name": "Test Family"})
    family_id = family_response.json()["id"]

    admin_member_response = client.post(
        f"/v1/families/{family_id}/members",
        json={
            "email": "parent@example.com",
            "display_name": "Parent",
            "role": "admin",
        },
    )
    child_member_response = client.post(
        f"/v1/families/{family_id}/members",
        json={
            "email": "child@example.com",
            "display_name": "Child",
            "role": "editor",
        },
    )
    admin_member_id = admin_member_response.json()["id"]
    child_member_id = child_member_response.json()["id"]
    person_map = _person_map(client, family_id)

    goal_a_response = client.post(
        "/v1/goals",
        json={
            "family_id": family_id,
            "scope_type": "family",
            "name": "Stability",
            "description": "Financial and schedule stability",
            "action_types": [],
            "weight": 0.6,
            "status": "active",
        },
    )
    goal_b_response = client.post(
        "/v1/goals",
        json={
            "family_id": family_id,
            "scope_type": "family",
            "name": "Family Time",
            "description": "Quality time together",
            "action_types": [],
            "weight": 0.4,
            "status": "active",
        },
    )

    return {
        "family_id": family_id,
        "admin_member_id": admin_member_id,
        "child_member_id": child_member_id,
        "admin_person_id": person_map[admin_member_id]["person_id"],
        "child_person_id": person_map[child_member_id]["person_id"],
        "goal_a_id": goal_a_response.json()["id"],
        "goal_b_id": goal_b_response.json()["id"],
    }


def test_create_score_and_queue_insert(client, db_session):
    ids = _seed_family_context(client)

    create_response = client.post(
        "/v1/decisions",
        json={
            "family_id": ids["family_id"],
            "created_by_person_id": ids["admin_person_id"],
            "scope_type": "family",
            "title": "Book summer trip",
            "description": "Plan a family trip for July",
            "urgency": 4,
            "tags": ["travel"],
        },
    )
    assert create_response.status_code == 201
    decision_id = create_response.json()["id"]

    patch_response = client.patch(
        f"/v1/decisions/{decision_id}",
        json={"notes": "updated via api", "cost": 300.0},
    )
    assert patch_response.status_code == 200
    assert patch_response.json()["notes"] == "updated via api"

    score_response = client.post(
        f"/v1/decisions/{decision_id}/score",
        json={
            "goal_scores": [
                {"goal_id": ids["goal_a_id"], "score_1_to_5": 5, "rationale": "well planned"},
                {"goal_id": ids["goal_b_id"], "score_1_to_5": 4, "rationale": "increases family time"},
            ],
            "threshold_1_to_5": 4.0,
            "computed_by": "human",
        },
    )

    assert score_response.status_code == 200
    body = score_response.json()
    assert body["routed_to"] == "queue"
    assert body["status"] == "Queued"
    assert body["queue_item_id"] is not None

    persisted_decision = db_session.get(Decision, decision_id)
    persisted_scores = db_session.query(DecisionScoreRun).filter(DecisionScoreRun.decision_id == decision_id).all()
    persisted_queue = db_session.query(DecisionQueueItem).filter(DecisionQueueItem.decision_id == decision_id).one_or_none()

    assert persisted_decision is not None
    assert persisted_decision.status.value == "Queued"
    assert len(persisted_scores) == 1
    assert persisted_queue is not None
    assert persisted_scores[0].weighted_total_1_to_5 == 4.6

    detail_response = client.get(f"/v1/decisions/{decision_id}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["latest_score_run"] is not None
    assert detail["latest_score_run"]["weighted_total_1_to_5"] == 4.6
    assert detail["latest_score_run"]["weighted_total_0_to_100"] == 90.0
    assert len(detail["latest_score_run"]["components"]) == 2

    goal_context_response = client.get(f"/v1/decisions/{decision_id}/goal-context")
    assert goal_context_response.status_code == 200
    assert len(goal_context_response.json()["family_goals"]) == 2
    assert goal_context_response.json()["person_goals"] == []

    list_response = client.get(f"/v1/decisions?family_id={ids['family_id']}&include_scores=true")
    assert list_response.status_code == 200
    assert list_response.json()["items"][0]["latest_score_run"] is not None


def test_create_score_below_threshold_routes_to_needs_work(client, db_session):
    ids = _seed_family_context(client)

    create_response = client.post(
        "/v1/decisions",
        json={
            "family_id": ids["family_id"],
            "created_by_person_id": ids["admin_person_id"],
            "title": "Buy expensive gadget",
            "description": "Considering a high-cost purchase",
            "urgency": 2,
        },
    )
    decision_id = create_response.json()["id"]

    score_response = client.post(
        f"/v1/decisions/{decision_id}/score",
        json={
            "goal_scores": [
                {"goal_id": ids["goal_a_id"], "score_1_to_5": 2, "rationale": "high cost risk"},
                {"goal_id": ids["goal_b_id"], "score_1_to_5": 3, "rationale": "neutral for time"},
            ],
            "threshold_1_to_5": 4.0,
            "computed_by": "human",
        },
    )

    assert score_response.status_code == 200
    body = score_response.json()
    assert body["routed_to"] == "needs_work"
    assert body["status"] == "Needs-Work"
    assert body["queue_item_id"] is None

    detail_response = client.get(f"/v1/decisions/{decision_id}")
    assert detail_response.status_code == 200
    assert detail_response.json()["latest_score_run"]["weighted_total_1_to_5"] == 2.4


def test_person_scoped_decision_scores_against_family_and_person_goals(client):
    ids = _seed_family_context(client)

    personal_goal_response = client.post(
        "/v1/goals",
        json={
            "family_id": ids["family_id"],
            "scope_type": "person",
            "owner_person_id": ids["child_person_id"],
            "visibility_scope": "personal",
            "name": "Run a 5K",
            "description": "Train consistently for a summer race",
            "weight": 0.5,
            "status": "active",
        },
    )
    assert personal_goal_response.status_code == 201
    personal_goal_id = personal_goal_response.json()["id"]

    create_response = client.post(
        "/v1/decisions",
        json={
            "family_id": ids["family_id"],
            "scope_type": "person",
            "created_by_person_id": ids["admin_person_id"],
            "owner_person_id": ids["child_person_id"],
            "target_person_id": ids["child_person_id"],
            "visibility_scope": "personal",
            "goal_policy": "family_plus_person",
            "title": "Join the youth 5K team",
            "description": "Decide whether to join structured training for the race",
            "urgency": 3,
        },
    )
    assert create_response.status_code == 201
    decision_id = create_response.json()["id"]

    goal_context_response = client.get(f"/v1/decisions/{decision_id}/goal-context")
    assert goal_context_response.status_code == 200
    goal_context = goal_context_response.json()
    assert goal_context["scope_type"] == "person"
    assert goal_context["goal_policy"] == "family_plus_person"
    assert len(goal_context["family_goals"]) == 2
    assert len(goal_context["person_goals"]) == 1

    score_response = client.post(
        f"/v1/decisions/{decision_id}/score",
        json={
            "goal_scores": [
                {"goal_id": ids["goal_a_id"], "score_1_to_5": 4, "rationale": "keeps routines and planning aligned"},
                {"goal_id": ids["goal_b_id"], "score_1_to_5": 5, "rationale": "creates healthy shared time"},
                {"goal_id": personal_goal_id, "score_1_to_5": 5, "rationale": "directly advances the child goal"},
            ],
            "threshold_1_to_5": 4.5,
            "computed_by": "human",
        },
    )
    assert score_response.status_code == 200
    score_body = score_response.json()
    assert score_body["routed_to"] == "queue"
    assert score_body["score_run"]["family_weighted_total_1_to_5"] == 4.4
    assert score_body["score_run"]["person_weighted_total_1_to_5"] == 5.0
    assert score_body["score_run"]["weighted_total_1_to_5"] == 4.6
    assert len(score_body["score_run"]["components"]) == 3

    history_response = client.get(f"/v1/decisions/{decision_id}/score-runs")
    assert history_response.status_code == 200
    assert len(history_response.json()["items"]) == 1
    assert history_response.json()["items"][0]["goal_policy"] == "family_plus_person"


def test_decision_routes_emit_canonical_family_events(client, monkeypatch):
    from app.routers import decisions as decisions_router

    ids = _seed_family_context(client)
    emitted: list[dict] = []

    def _capture(**kwargs):
        emitted.append(kwargs)

    monkeypatch.setattr(decisions_router, "_emit_decision_event", _capture)

    create_response = client.post(
        "/v1/decisions",
        json={
            "family_id": ids["family_id"],
            "created_by_person_id": ids["admin_person_id"],
            "title": "Replace roof",
            "description": "Major repair",
            "urgency": 5,
        },
    )
    assert create_response.status_code == 201
    decision_id = create_response.json()["id"]

    assert emitted[-1]["event_type"] == "decision.created"

    patch_response = client.patch(
        f"/v1/decisions/{decision_id}",
        json={"notes": "updated via canonical event test"},
    )
    assert patch_response.status_code == 200
    assert emitted[-1]["event_type"] == "decision.updated"

    score_response = client.post(
        f"/v1/decisions/{decision_id}/score",
        json={
            "goal_scores": [
                {"goal_id": ids["goal_a_id"], "score_1_to_5": 5, "rationale": "important"},
                {"goal_id": ids["goal_b_id"], "score_1_to_5": 4, "rationale": "helps family"},
            ],
            "threshold_1_to_5": 4.0,
            "computed_by": "human",
        },
    )
    assert score_response.status_code == 200
    score_event_types = [item["event_type"] for item in emitted]
    assert "decision.score_calculated" in score_event_types
    assert "decision.score_above_threshold" in score_event_types

    complete_response = client.post(
        f"/v1/decisions/{decision_id}/status",
        params={"status": DecisionStatusEnum.done.value},
    )
    assert complete_response.status_code == 200

    delete_response = client.delete(f"/v1/decisions/{decision_id}")
    assert delete_response.status_code == 204

    final_event_types = [item["event_type"] for item in emitted]
    assert "decision.updated" in final_event_types
    assert "decision.completed" in final_event_types
    assert "decision.deleted" in final_event_types
