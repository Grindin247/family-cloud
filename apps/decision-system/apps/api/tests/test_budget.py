def _seed_family_with_members(client):
    family = client.post("/v1/families", json={"name": "Budget Family"}).json()
    member_a = client.post(
        f"/v1/families/{family['id']}/members",
        json={"email": "a@example.com", "display_name": "Member A", "role": "editor"},
    ).json()
    member_b = client.post(
        f"/v1/families/{family['id']}/members",
        json={"email": "b@example.com", "display_name": "Member B", "role": "editor"},
    ).json()
    return family, member_a, member_b


def test_budget_summary_handles_overlapping_periods(client, db_session):
    from datetime import date

    from app.models.entities import Period, PeriodTypeEnum

    family, _, _ = _seed_family_with_members(client)
    db_session.add(
        Period(
            family_id=family["id"],
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            type=PeriodTypeEnum.custom,
        )
    )
    db_session.add(
        Period(
            family_id=family["id"],
            start_date=date(2026, 6, 1),
            end_date=date(2026, 12, 31),
            type=PeriodTypeEnum.custom,
        )
    )
    db_session.commit()

    summary = client.get(f"/v1/budgets/families/{family['id']}")
    assert summary.status_code == 200
    assert "members" in summary.json()


def test_budget_summary_and_policy_update(client):
    family, member_a, member_b = _seed_family_with_members(client)

    summary = client.get(f"/v1/budgets/families/{family['id']}")
    assert summary.status_code == 200
    body = summary.json()
    assert body["default_allowance"] == 2
    assert len(body["members"]) == 2

    update = client.put(
        f"/v1/budgets/families/{family['id']}/policy",
        json={
            "threshold_1_to_5": 3.8,
            "period_days": 30,
            "default_allowance": 3,
            "member_allowances": [
                {"member_id": member_a["id"], "allowance": 4},
                {"member_id": member_b["id"], "allowance": 1},
            ],
        },
    )
    assert update.status_code == 200
    updated = update.json()
    assert updated["threshold_1_to_5"] == 3.8
    assert updated["period_days"] == 30
    by_member = {item["member_id"]: item for item in updated["members"]}
    assert by_member[member_a["id"]]["allowance"] == 4
    assert by_member[member_b["id"]]["allowance"] == 1


def test_budget_reset_period_reallocates_allowance(client):
    family, _, _ = _seed_family_with_members(client)

    first = client.get(f"/v1/budgets/families/{family['id']}").json()
    reset = client.post(f"/v1/budgets/families/{family['id']}/period/reset")
    assert reset.status_code == 200
    second = reset.json()

    assert first["period_days"] == second["period_days"]
    assert sum(item["used"] for item in second["members"]) == 0
