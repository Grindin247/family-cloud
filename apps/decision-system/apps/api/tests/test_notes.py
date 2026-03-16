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


def test_note_index_and_search_lexical(client, db_session):
    family = _seed_family(db_session)

    index_response = client.post(
        "/v1/notes/index",
        headers={"X-Dev-User": "u@example.com"},
        json={
            "family_id": family.id,
            "actor": "u@example.com",
            "source_session_id": "notes-1",
            "path": "/Notes/FamilyCloud/Areas/Church/2026-02-22-sunday-service.md",
            "item_type": "polished",
            "role": "polished",
            "title": "Sunday Service",
            "summary": "Notes from Sunday service.",
            "body_text": "We learned about faithful obedience and prayer.",
            "excerpt_text": "faithful obedience and prayer",
            "content_type": "text/markdown",
            "source_date": "2026-02-22",
            "tags": ["church", "service"],
            "nextcloud_url": "https://nextcloud.example/polished",
            "raw_note_url": "https://nextcloud.example/raw",
            "related_paths": ["/Notes/FamilyCloud/Archive/Raw/Church/2026/2026-02-22-sunday-service-raw.md"],
            "metadata": {"destination": "Areas"},
        },
    )
    assert index_response.status_code == 201

    raw_index_response = client.post(
        "/v1/notes/index",
        headers={"X-Dev-User": "u@example.com"},
        json={
            "family_id": family.id,
            "actor": "u@example.com",
            "source_session_id": "notes-1",
            "path": "/Notes/FamilyCloud/Archive/Raw/Church/2026/2026-02-22-sunday-service-raw.md",
            "item_type": "raw",
            "role": "archive",
            "title": "Sunday Service Raw",
            "summary": "Raw sermon notes.",
            "body_text": "Raw sermon notes with scripture references.",
            "excerpt_text": "scripture references",
            "content_type": "text/markdown",
            "source_date": "2026-02-22",
            "tags": ["church"],
            "nextcloud_url": "https://nextcloud.example/raw-file",
            "raw_note_url": "https://nextcloud.example/raw-file",
            "related_paths": ["/Notes/FamilyCloud/Areas/Church/2026-02-22-sunday-service.md"],
            "metadata": {},
        },
    )
    assert raw_index_response.status_code == 201

    search_response = client.post(
        "/v1/notes/search",
        headers={"X-Dev-User": "u@example.com"},
        json={
            "family_id": family.id,
            "actor": "u@example.com",
            "query": "what did i learn in sunday service",
            "top_k": 5,
            "query_tags": ["church"],
            "include_content": True,
        },
    )
    assert search_response.status_code == 200
    body = search_response.json()
    assert body["items"][0]["item_type"] == "polished"
    assert body["items"][0]["raw_note_url"] == "https://nextcloud.example/raw"
    assert body["items"][0]["match_reasons"]


def test_note_search_returns_empty_for_other_family(client, db_session):
    family = _seed_family(db_session)
    other = Family(name="Other Family")
    db_session.add(other)
    db_session.flush()
    db_session.add(
        FamilyMember(
            family_id=other.id,
            email="other@example.com",
            display_name="Other",
            role=RoleEnum.admin,
        )
    )
    db_session.commit()

    client.post(
        "/v1/notes/index",
        headers={"X-Dev-User": "u@example.com"},
        json={
            "family_id": family.id,
            "actor": "u@example.com",
            "path": "/Notes/FamilyCloud/Projects/2026-03-01-kitchen-remodel.md",
            "item_type": "polished",
            "role": "polished",
            "title": "Kitchen remodel",
            "summary": "Contractor estimate",
            "body_text": "Estimate and permit notes.",
            "excerpt_text": "Estimate and permit notes.",
            "content_type": "text/markdown",
            "tags": ["projects"],
            "related_paths": [],
            "metadata": {},
        },
    )

    response = client.post(
        "/v1/notes/search",
        headers={"X-Dev-User": "other@example.com"},
        json={
            "family_id": other.id,
            "actor": "other@example.com",
            "query": "kitchen remodel",
            "top_k": 5,
        },
    )
    assert response.status_code == 200
    assert response.json()["items"] == []


def test_note_index_normalizes_redundant_adjacent_path_segments(client, db_session):
    family = _seed_family(db_session)
    response = client.post(
        "/v1/notes/index",
        headers={"X-Dev-User": "u@example.com"},
        json={
            "family_id": family.id,
            "actor": "u@example.com",
            "path": "/Notes/FamilyCloud/Area/Area/School/weekly-update.md",
            "item_type": "polished",
            "role": "polished",
            "title": "Weekly Update",
            "summary": "School notes.",
            "body_text": "This week at school...",
            "related_paths": [
                "/Notes/FamilyCloud/Area/Area/School/raw.md",
                "/Notes/FamilyCloud/Area/School/raw.md",
            ],
            "metadata": {},
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["path"] == "/Notes/FamilyCloud/Area/School/weekly-update.md"

    search_response = client.post(
        "/v1/notes/search",
        headers={"X-Dev-User": "u@example.com"},
        json={
            "family_id": family.id,
            "actor": "u@example.com",
            "query": "weekly school update",
            "top_k": 5,
        },
    )
    assert search_response.status_code == 200
    item = search_response.json()["items"][0]
    assert item["path"] == "/Notes/FamilyCloud/Area/School/weekly-update.md"
    assert item["related_paths"] == ["/Notes/FamilyCloud/Area/School/raw.md"]
