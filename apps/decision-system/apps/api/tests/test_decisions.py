from app.models.entities import (
    Decision,
    DecisionQueueItem,
    DecisionScore,
)


def _seed_family_context(client):
    family_response = client.post("/v1/families", json={"name": "Test Family"})
    family_id = family_response.json()["id"]

    member_response = client.post(
        f"/v1/families/{family_id}/members",
        json={
            "email": "parent@example.com",
            "display_name": "Parent",
            "role": "editor",
        },
    )
    member_id = member_response.json()["id"]

    goal_a_response = client.post(
        "/v1/goals",
        json={
            "family_id": family_id,
            "name": "Stability",
            "description": "Financial and schedule stability",
            "action_types": [],
            "weight": 0.6,
            "active": True,
        },
    )
    goal_b_response = client.post(
        "/v1/goals",
        json={
            "family_id": family_id,
            "name": "Family Time",
            "description": "Quality time together",
            "action_types": [],
            "weight": 0.4,
            "active": True,
        },
    )

    return {
        "family_id": family_id,
        "member_id": member_id,
        "goal_a_id": goal_a_response.json()["id"],
        "goal_b_id": goal_b_response.json()["id"],
    }


def test_create_score_and_queue_insert(client, db_session):
    ids = _seed_family_context(client)

    create_response = client.post(
        "/v1/decisions",
        json={
            "family_id": ids["family_id"],
            "created_by_member_id": ids["member_id"],
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
    persisted_scores = db_session.query(DecisionScore).filter(DecisionScore.decision_id == decision_id).all()
    persisted_queue = db_session.query(DecisionQueueItem).filter(DecisionQueueItem.decision_id == decision_id).one_or_none()

    assert persisted_decision is not None
    assert persisted_decision.status.value == "Queued"
    assert len(persisted_scores) == 2
    assert persisted_queue is not None

    detail_response = client.get(f"/v1/decisions/{decision_id}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["score_summary"] is not None
    assert detail["score_summary"]["weighted_total_1_to_5"] == 4.6
    assert detail["score_summary"]["weighted_total_0_to_100"] == 90.0
    assert len(detail["score_summary"]["goal_scores"]) == 2

    list_response = client.get(f"/v1/decisions?family_id={ids['family_id']}&include_scores=true")
    assert list_response.status_code == 200
    assert list_response.json()["items"][0]["score_summary"] is not None


def test_create_score_below_threshold_routes_to_needs_work(client, db_session):
    ids = _seed_family_context(client)

    create_response = client.post(
        "/v1/decisions",
        json={
            "family_id": ids["family_id"],
            "created_by_member_id": ids["member_id"],
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
    assert detail_response.json()["score_summary"]["weighted_total_1_to_5"] == 2.4
