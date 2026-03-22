def _headers():
    return {"X-Dev-User": "admin@example.com"}


def test_profile_crud_and_relationship_flow(client):
    viewer = client.get("/v1/me", headers=_headers())
    assert viewer.status_code == 200
    assert viewer.json()["email"] == "admin@example.com"

    context = client.get("/v1/families/2/viewer-context", headers=_headers())
    assert context.status_code == 200
    assert context.json()["profile_enabled"] is True

    listed = client.get("/v1/families/2/profiles", headers=_headers())
    assert listed.status_code == 200
    assert len(listed.json()["items"]) == 2

    payload = {
        "account_profile": {
            "primary_login": "rachel.c.griffin@gmail.com",
            "auth_providers": ["keycloak"],
            "auth_methods": ["password", "passkey"],
            "mfa_enabled": True,
            "passkeys_enabled": True,
            "passkey_labels": ["Family laptop"],
            "recovery_methods": ["backup-codes"],
            "recovery_contacts": ["admin@example.com"],
            "legal_consents": [{"consent_key": "telehealth", "status": "granted"}],
            "security_notes": "Reviewed this week.",
            "last_reviewed_at": "2026-03-21T12:00:00Z",
        },
        "person_profile": {
            "birthdate": "2015-04-10",
            "pronouns": "she/her",
            "timezone": "America/New_York",
            "locale": "en-US",
            "languages": ["English"],
            "role_tags": ["child"],
            "traits": ["curious", "musical"],
            "demographic_notes": "Learner profile seed.",
        },
        "preferences": {
            "hobbies": ["piano", "drawing"],
            "interests": ["animals", "science"],
            "learning_preferences": {
                "modalities": ["visual", "hands-on"],
                "pace": "gentle ramp-up",
                "environments": ["quiet room"],
                "supports": ["preview the plan"],
                "notes": "Needs warm starts.",
            },
            "dietary_preferences": {
                "restrictions": ["no peanuts"],
                "allergies": ["peanuts"],
                "likes": ["berries"],
                "dislikes": ["mushrooms"],
                "notes": "Keep snacks simple.",
            },
            "accessibility_needs": {
                "accommodations": ["reduced noise"],
                "assistive_tools": ["visual timer"],
                "sensory_considerations": ["headphones"],
                "mobility_considerations": [],
                "notes": "Transitions are easier with notice.",
            },
            "motivation_style": {
                "encouragements": ["specific praise"],
                "rewards": ["extra art time"],
                "triggers_to_avoid": ["public pressure"],
                "routines": ["short check-ins"],
                "notes": "Responds to calm energy.",
            },
            "communication_preferences": {
                "preferred_channels": ["in-person", "text"],
                "response_style": "brief and warm",
                "cadence": "after school",
                "boundaries": ["avoid late-night asks"],
                "notes": "Prefers one change at a time.",
            },
        },
    }
    updated = client.put(
        "/v1/families/2/profiles/00000000-0000-0000-0000-000000000011",
        json=payload,
        headers=_headers(),
    )
    assert updated.status_code == 200
    detail = updated.json()
    assert detail["person_profile"]["role_tags"] == ["child"]
    assert detail["preferences"]["hobbies"] == ["piano", "drawing"]
    assert detail["account_profile"]["mfa_enabled"] is True

    relationship = client.post(
        "/v1/families/2/relationships",
        json={
            "source_person_id": "00000000-0000-0000-0000-000000000010",
            "target_person_id": "00000000-0000-0000-0000-000000000011",
            "relationship_type": "guardian",
            "status": "active",
            "is_mutual": False,
            "notes": "Primary school-day contact",
            "metadata": {"context": "weekday pickup"},
        },
        headers=_headers(),
    )
    assert relationship.status_code == 200
    relationship_id = relationship.json()["relationship_id"]

    detail_after_relationship = client.get(
        "/v1/families/2/profiles/00000000-0000-0000-0000-000000000011",
        headers=_headers(),
    )
    assert detail_after_relationship.status_code == 200
    assert len(detail_after_relationship.json()["relationships"]) == 1
    assert detail_after_relationship.json()["relationships"][0]["relationship_type"] == "guardian"

    updated_relationship = client.put(
        f"/v1/families/2/relationships/{relationship_id}",
        json={
            "source_person_id": "00000000-0000-0000-0000-000000000010",
            "target_person_id": "00000000-0000-0000-0000-000000000011",
            "relationship_type": "delegated_caregiver",
            "status": "active",
            "is_mutual": False,
            "notes": "Pickup backup",
            "metadata": {"context": "after-school"},
        },
        headers=_headers(),
    )
    assert updated_relationship.status_code == 200
    assert updated_relationship.json()["relationship_type"] == "delegated_caregiver"

    deleted = client.delete(f"/v1/families/2/relationships/{relationship_id}", headers=_headers())
    assert deleted.status_code == 204
    relationships = client.get(
        "/v1/families/2/relationships",
        params={"person_id": "00000000-0000-0000-0000-000000000011"},
        headers=_headers(),
    )
    assert relationships.status_code == 200
    assert relationships.json()["items"] == []


def test_profile_feature_context_and_toggle(client, monkeypatch):
    monkeypatch.setattr(
        "app.routers.profile.get_family_features",
        lambda **kwargs: [
            {
                "family_id": kwargs["family_id"],
                "feature_key": "profile",
                "enabled": False,
                "config": {},
                "updated_at": "2026-03-21T12:00:00Z",
            }
        ],
    )
    context = client.get("/v1/families/2/viewer-context", headers=_headers())
    assert context.status_code == 200
    assert context.json()["profile_enabled"] is False

    toggled = client.put("/v1/families/2/profile-feature", json={"enabled": True, "config": {}}, headers=_headers())
    assert toggled.status_code == 200
    assert toggled.json()["feature_key"] == "profile"
    assert toggled.json()["enabled"] is True
