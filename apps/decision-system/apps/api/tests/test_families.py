def test_family_and_member_crud(client):
    create_family = client.post("/v1/families", json={"name": "Household"})
    assert create_family.status_code == 201
    family_id = create_family.json()["id"]

    list_families = client.get("/v1/families")
    assert list_families.status_code == 200
    assert len(list_families.json()["items"]) == 1

    update_family = client.patch(f"/v1/families/{family_id}", json={"name": "Household Prime"})
    assert update_family.status_code == 200
    assert update_family.json()["name"] == "Household Prime"

    create_member = client.post(
        f"/v1/families/{family_id}/members",
        json={
            "email": "admin@example.com",
            "display_name": "Admin",
            "role": "admin",
        },
    )
    assert create_member.status_code == 201
    member_id = create_member.json()["id"]

    list_members = client.get(f"/v1/families/{family_id}/members")
    assert list_members.status_code == 200
    assert len(list_members.json()["items"]) == 1

    get_member = client.get(f"/v1/families/{family_id}/members/{member_id}")
    assert get_member.status_code == 200
    assert get_member.json()["email"] == "admin@example.com"

    update_member = client.patch(
        f"/v1/families/{family_id}/members/{member_id}",
        json={"display_name": "Editor", "role": "editor"},
    )
    assert update_member.status_code == 200
    assert update_member.json()["role"] == "editor"

    duplicate_member = client.post(
        f"/v1/families/{family_id}/members",
        json={
            "email": "admin@example.com",
            "display_name": "Duplicate",
            "role": "viewer",
        },
    )
    assert duplicate_member.status_code == 409

    delete_family = client.delete(f"/v1/families/{family_id}")
    assert delete_family.status_code == 204

    # Family delete should purge dependent members as well.
    list_families = client.get("/v1/families")
    assert list_families.status_code == 200
    assert len(list_families.json()["items"]) == 0
