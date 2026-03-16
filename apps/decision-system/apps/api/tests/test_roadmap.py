def test_roadmap_requires_threshold_or_discretionary_budget(client):
    family = client.post("/v1/families", json={"name": "Roadmap Family"}).json()
    member = client.post(
        f"/v1/families/{family['id']}/members",
        json={"email": "roadmap@example.com", "display_name": "Planner", "role": "editor"},
    ).json()
    decision = client.post(
        "/v1/decisions",
        json={
            "family_id": family["id"],
            "created_by_member_id": member["id"],
            "title": "Quarterly planning",
            "description": "Plan priorities",
        },
    ).json()

    blocked = client.post(
        "/v1/roadmap",
        json={
            "decision_id": decision["id"],
            "bucket": "2026-Q2",
            "status": "Scheduled",
            "dependencies": [],
        },
    )
    assert blocked.status_code == 400

    create = client.post(
        "/v1/roadmap",
        json={
            "decision_id": decision["id"],
            "bucket": "2026-Q2",
            "status": "Scheduled",
            "dependencies": [],
            "use_discretionary_budget": True,
        },
    )
    assert create.status_code == 201
    roadmap_id = create.json()["id"]

    list_response = client.get(f"/v1/roadmap?family_id={family['id']}")
    assert list_response.status_code == 200
    assert len(list_response.json()["items"]) == 1

    update = client.patch(
        f"/v1/roadmap/{roadmap_id}",
        json={"status": "In-Progress", "dependencies": [999]},
    )
    assert update.status_code == 200
    assert update.json()["status"] == "In-Progress"
    assert update.json()["dependencies"] == [999]

    delete = client.delete(f"/v1/roadmap/{roadmap_id}")
    assert delete.status_code == 204


def test_roadmap_discretionary_budget_limit_enforced(client):
    family = client.post("/v1/families", json={"name": "Budget Limited Family"}).json()
    member = client.post(
        f"/v1/families/{family['id']}/members",
        json={"email": "limit@example.com", "display_name": "Limiter", "role": "editor"},
    ).json()

    policy_update = client.put(
        f"/v1/budgets/families/{family['id']}/policy",
        json={
            "threshold_1_to_5": 4.0,
            "period_days": 30,
            "default_allowance": 1,
            "member_allowances": [{"member_id": member["id"], "allowance": 1}],
        },
    )
    assert policy_update.status_code == 200

    decision_a = client.post(
        "/v1/decisions",
        json={
            "family_id": family["id"],
            "created_by_member_id": member["id"],
            "title": "Need Work A",
            "description": "Below threshold decision A",
        },
    ).json()
    decision_b = client.post(
        "/v1/decisions",
        json={
            "family_id": family["id"],
            "created_by_member_id": member["id"],
            "title": "Need Work B",
            "description": "Below threshold decision B",
        },
    ).json()

    first = client.post(
        "/v1/roadmap",
        json={
            "decision_id": decision_a["id"],
            "bucket": "2026-Q2",
            "status": "Scheduled",
            "dependencies": [],
            "use_discretionary_budget": True,
        },
    )
    assert first.status_code == 201

    second = client.post(
        "/v1/roadmap",
        json={
            "decision_id": decision_b["id"],
            "bucket": "2026-Q2",
            "status": "Scheduled",
            "dependencies": [],
            "use_discretionary_budget": True,
        },
    )
    assert second.status_code == 400
    assert "exhausted" in second.json()["detail"]


def test_unschedule_before_done_refunds_discretionary_budget(client):
    family = client.post("/v1/families", json={"name": "Refund Family"}).json()
    member = client.post(
        f"/v1/families/{family['id']}/members",
        json={"email": "refund@example.com", "display_name": "Refunder", "role": "editor"},
    ).json()

    client.put(
        f"/v1/budgets/families/{family['id']}/policy",
        json={
            "threshold_1_to_5": 4.0,
            "period_days": 30,
            "default_allowance": 2,
            "member_allowances": [{"member_id": member["id"], "allowance": 2}],
        },
    )

    decision = client.post(
        "/v1/decisions",
        json={
            "family_id": family["id"],
            "created_by_member_id": member["id"],
            "title": "Refundable decision",
            "description": "Should refund when unscheduled",
        },
    ).json()

    scheduled = client.post(
        "/v1/roadmap",
        json={
            "decision_id": decision["id"],
            "bucket": "2026-Q2",
            "status": "Scheduled",
            "dependencies": [],
            "use_discretionary_budget": True,
        },
    )
    assert scheduled.status_code == 201
    roadmap_id = scheduled.json()["id"]

    mid_summary = client.get(f"/v1/budgets/families/{family['id']}").json()
    member_summary = next(item for item in mid_summary["members"] if item["member_id"] == member["id"])
    assert member_summary["used"] == 1
    assert member_summary["remaining"] == 1

    deleted = client.delete(f"/v1/roadmap/{roadmap_id}")
    assert deleted.status_code == 204

    final_summary = client.get(f"/v1/budgets/families/{family['id']}").json()
    member_summary = next(item for item in final_summary["members"] if item["member_id"] == member["id"])
    assert member_summary["used"] == 0
    assert member_summary["remaining"] == 2


def test_unschedule_after_done_does_not_refund_discretionary_budget(client):
    family = client.post("/v1/families", json={"name": "No Refund Family"}).json()
    member = client.post(
        f"/v1/families/{family['id']}/members",
        json={"email": "norefund@example.com", "display_name": "No Refund", "role": "editor"},
    ).json()

    client.put(
        f"/v1/budgets/families/{family['id']}/policy",
        json={
            "threshold_1_to_5": 4.0,
            "period_days": 30,
            "default_allowance": 2,
            "member_allowances": [{"member_id": member["id"], "allowance": 2}],
        },
    )

    decision = client.post(
        "/v1/decisions",
        json={
            "family_id": family["id"],
            "created_by_member_id": member["id"],
            "title": "Completed decision",
            "description": "Done should not refund",
        },
    ).json()

    scheduled = client.post(
        "/v1/roadmap",
        json={
            "decision_id": decision["id"],
            "bucket": "2026-Q2",
            "status": "Scheduled",
            "dependencies": [],
            "use_discretionary_budget": True,
        },
    )
    assert scheduled.status_code == 201
    roadmap_id = scheduled.json()["id"]

    mark_done = client.patch(f"/v1/roadmap/{roadmap_id}", json={"status": "Done"})
    assert mark_done.status_code == 200

    deleted = client.delete(f"/v1/roadmap/{roadmap_id}")
    assert deleted.status_code == 204

    final_summary = client.get(f"/v1/budgets/families/{family['id']}").json()
    member_summary = next(item for item in final_summary["members"] if item["member_id"] == member["id"])
    assert member_summary["used"] == 1
    assert member_summary["remaining"] == 1
