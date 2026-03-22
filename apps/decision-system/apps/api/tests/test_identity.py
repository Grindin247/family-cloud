from app.models.entities import Family, FamilyMember, RoleEnum


def test_list_persons_backfills_from_family_members(client, db_session):
    family = Family(name="Callender Family", slug="callender-family")
    db_session.add(family)
    db_session.flush()
    db_session.add(
        FamilyMember(
            family_id=family.id,
            email="mrjamescallender@gmail.com",
            display_name="James",
            role=RoleEnum.admin,
            external_source="keycloak",
            external_id="kc-james",
        )
    )
    db_session.commit()

    response = client.get(f"/v1/families/{family.id}/persons")
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["display_name"] == "James"
    assert "dadda" in [alias.lower() for alias in items[0]["aliases"]]
    assert items[0]["accounts"]["email"] == ["mrjamescallender@gmail.com"]


def test_resolve_alias_prefers_seeded_aliases(client, db_session):
    family = Family(name="Callender Family", slug="callender-family")
    db_session.add(family)
    db_session.flush()
    db_session.add(
        FamilyMember(
            family_id=family.id,
            email="mrjamescallender@gmail.com",
            display_name="James",
            role=RoleEnum.admin,
        )
    )
    db_session.commit()

    client.get(f"/v1/families/{family.id}/persons")
    response = client.get(f"/v1/families/{family.id}/resolve-alias", params={"q": "biscuithead"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["display_name"] == "James"
    assert payload["resolution_source"].startswith("exact_alias")


def test_sender_resolution_uses_person_accounts(client, db_session):
    family = Family(name="Callender Family", slug="callender-family")
    db_session.add(family)
    db_session.flush()
    db_session.add(
        FamilyMember(
            family_id=family.id,
            email="mrjamescallender@gmail.com",
            display_name="James",
            role=RoleEnum.admin,
        )
    )
    db_session.commit()
    persons = client.get(f"/v1/families/{family.id}/persons").json()["items"]
    person_id = persons[0]["person_id"]

    from app.services.identity import parse_person_id, upsert_person_account
    from app.models.identity import Person

    person = db_session.get(Person, parse_person_id(person_id))
    upsert_person_account(
        db_session,
        family_id=family.id,
        person=person,
        account_type="discord_sender_id",
        account_value="525687139737010177",
        is_primary=True,
    )
    db_session.commit()

    response = client.post(
        "/v1/identity/resolve-sender",
        json={
            "family_id": family.id,
            "source_channel": "discord",
            "source_sender_id": "525687139737010177",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["display_name"] == "James"
    assert payload["resolution_source"] == "sender_account"


def test_feature_flag_can_disable_decision_domain(client, db_session):
    family = Family(name="Callender Family", slug="callender-family")
    db_session.add(family)
    db_session.flush()
    db_session.add(
        FamilyMember(
            family_id=family.id,
            email="admin@example.com",
            display_name="Admin",
            role=RoleEnum.admin,
        )
    )
    db_session.commit()

    update = client.put(f"/v1/families/{family.id}/features/decision", json={"enabled": False, "config": {}})
    assert update.status_code == 200

    response = client.get("/v1/goals", params={"family_id": family.id})
    assert response.status_code == 404


def test_feature_listing_includes_profile_domain(client, db_session):
    family = Family(name="Callender Family", slug="callender-family")
    db_session.add(family)
    db_session.flush()
    db_session.add(
        FamilyMember(
            family_id=family.id,
            email="admin@example.com",
            display_name="Admin",
            role=RoleEnum.admin,
        )
    )
    db_session.commit()

    response = client.get(f"/v1/families/{family.id}/features")
    assert response.status_code == 200
    keys = {item["feature_key"] for item in response.json()["items"]}
    assert "profile" in keys


def test_resolved_context_returns_person_contract(client, db_session):
    family = Family(name="Callender Family", slug="callender-family")
    db_session.add(family)
    db_session.flush()
    db_session.add(
        FamilyMember(
            family_id=family.id,
            email="admin@example.com",
            display_name="Admin",
            role=RoleEnum.admin,
            external_source="keycloak",
            external_id="kc-admin",
        )
    )
    db_session.commit()

    response = client.get(
        f"/v1/families/{family.id}/context",
        headers={"X-Dev-User": "admin@example.com"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["family_id"] == family.id
    assert payload["family_slug"] == "callender-family"
    assert payload["person_id"] == payload["actor_person_id"]
    assert payload["target_person_id"] == payload["person_id"]
    assert payload["is_family_admin"] is True
    assert payload["directory_account_id"] == "kc-admin"
    assert payload["primary_email"] == "admin@example.com"


def test_account_mapping_can_authorize_family_access(client, db_session):
    family = Family(name="Callender Family", slug="callender-family")
    db_session.add(family)
    db_session.flush()
    db_session.add(
        FamilyMember(
            family_id=family.id,
            email="rachel@example.com",
            display_name="Rachel",
            role=RoleEnum.admin,
        )
    )
    db_session.commit()

    from app.services.identity import ensure_person_for_member, upsert_person_account

    member = db_session.query(FamilyMember).filter(FamilyMember.family_id == family.id).one()
    person = ensure_person_for_member(db_session, member)
    upsert_person_account(
        db_session,
        family_id=family.id,
        person=person,
        account_type="openclaw_sender_key",
        account_value="r.callender",
        is_primary=True,
    )
    db_session.commit()

    response = client.get(
        f"/v1/families/{family.id}/context",
        headers={"X-Dev-User": "r.callender"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["primary_email"] == "rachel@example.com"
    assert payload["person_id"] == str(person.person_id)
