def test_create_and_list_goals(client):
    family_response = client.post("/v1/families", json={"name": "Test Family"})
    assert family_response.status_code == 201
    family_id = family_response.json()["id"]

    create_response = client.post(
        "/v1/goals",
        json={
            "family_id": family_id,
            "name": "Family Time",
            "description": "Protect quality time",
            "weight": 0.7,
            "action_types": ["weekend", "evening"],
            "active": True,
        },
    )

    assert create_response.status_code == 201
    goal_id = create_response.json()["id"]

    update_response = client.patch(
        f"/v1/goals/{goal_id}",
        json={"weight": 0.8, "active": False},
    )
    assert update_response.status_code == 200
    assert update_response.json()["weight"] == 0.8
    assert update_response.json()["active"] is False

    list_response = client.get(f"/v1/goals?family_id={family_id}")
    assert list_response.status_code == 200
    assert len(list_response.json()["items"]) == 1

    delete_response = client.delete(f"/v1/goals/{goal_id}")
    assert delete_response.status_code == 204
