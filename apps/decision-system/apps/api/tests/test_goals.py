def _seed_family_with_person(client):
    family = client.post("/v1/families", json={"name": "Goals Family"}).json()
    member = client.post(
        f"/v1/families/{family['id']}/members",
        json={"email": "goals@example.com", "display_name": "Goal Keeper", "role": "admin"},
    ).json()
    persons = client.get(f"/v1/families/{family['id']}/persons").json()["items"]
    person = next(item for item in persons if item["legacy_member_id"] == member["id"])
    return family, member, person


def test_family_and_person_goal_lifecycle(client):
    family, _, person = _seed_family_with_person(client)

    family_goal = client.post(
        "/v1/goals",
        json={
            "family_id": family["id"],
            "scope_type": "family",
            "name": "Family Time",
            "description": "Protect quality time",
            "weight": 0.7,
            "action_types": ["weekend", "evening"],
            "status": "active",
            "priority": 4,
        },
    )
    assert family_goal.status_code == 201

    personal_goal = client.post(
        "/v1/goals",
        json={
            "family_id": family["id"],
            "scope_type": "person",
            "owner_person_id": person["person_id"],
            "visibility_scope": "personal",
            "name": "Run a 5K",
            "description": "Build stamina for a summer 5K",
            "weight": 0.5,
            "action_types": ["fitness"],
            "status": "active",
            "priority": 5,
            "success_criteria": "Run 5K without stopping",
            "tags": ["health"],
        },
    )
    assert personal_goal.status_code == 201
    personal_goal_id = personal_goal.json()["id"]

    update_response = client.patch(
        f"/v1/goals/{personal_goal_id}",
        json={"weight": 0.8, "status": "paused", "review_cadence_days": 14},
    )
    assert update_response.status_code == 200
    assert update_response.json()["weight"] == 0.8
    assert update_response.json()["status"] == "paused"
    assert update_response.json()["goal_revision"] == 2

    list_response = client.get(f"/v1/goals?family_id={family['id']}")
    assert list_response.status_code == 200
    assert len(list_response.json()["items"]) == 2

    personal_list = client.get(
        f"/v1/goals?family_id={family['id']}&scope_type=person&owner_person_id={person['person_id']}"
    )
    assert personal_list.status_code == 200
    assert len(personal_list.json()["items"]) == 1
    assert personal_list.json()["items"][0]["name"] == "Run a 5K"

    delete_response = client.delete(f"/v1/goals/{personal_goal_id}")
    assert delete_response.status_code == 204

    remaining = client.get(f"/v1/goals?family_id={family['id']}")
    assert remaining.status_code == 200
    assert len(remaining.json()["items"]) == 1

    deleted = client.get(
        f"/v1/goals?family_id={family['id']}&scope_type=person&owner_person_id={person['person_id']}&include_deleted=true"
    )
    assert deleted.status_code == 200
    assert len(deleted.json()["items"]) == 1
    assert deleted.json()["items"][0]["deleted_at"] is not None
