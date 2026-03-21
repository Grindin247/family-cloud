from __future__ import annotations

from app.models.entities import Family, FamilyMember, RoleEnum


def _seed_family(db_session):
    family = Family(name="Family")
    db_session.add(family)
    db_session.flush()
    db_session.add(
        FamilyMember(
            family_id=family.id,
            email="u@example.com",
            display_name="User",
            role=RoleEnum.admin,
        )
    )
    db_session.commit()
    return family


def test_memory_source_refs_round_trip_through_search(client, db_session):
    family = _seed_family(db_session)

    create_response = client.post(
        f"/v1/family/{family.id}/memory/documents",
        headers={"X-Dev-User": "u@example.com"},
        json={
            "family_id": family.id,
            "type": "note",
            "text": "Kitchen remodel notes with permit questions and contractor follow-up.",
            "source_refs": [
                {
                    "type": "nextcloud_file",
                    "title": "Kitchen Remodel Notes",
                    "path": "/Notes/Projects/2026-03-20_kitchen-remodel-notes.md",
                    "url": "https://nextcloud.example/apps/files/files/Notes/Projects/2026-03-20_kitchen-remodel-notes.md",
                }
            ],
        },
    )
    assert create_response.status_code == 201
    assert create_response.json()["source_refs"][0]["path"] == "/Notes/Projects/2026-03-20_kitchen-remodel-notes.md"

    search_response = client.post(
        f"/v1/family/{family.id}/memory/search",
        json={
            "query": "permit questions",
            "top_k": 5,
        },
    )
    assert search_response.status_code == 200
    body = search_response.json()
    assert body["items"]
    assert body["items"][0]["source_refs"][0]["title"] == "Kitchen Remodel Notes"
    assert body["items"][0]["source_refs"][0]["url"].startswith("https://nextcloud.example/")
