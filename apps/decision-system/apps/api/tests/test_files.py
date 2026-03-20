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


def test_file_index_and_search(client, db_session):
    family = _seed_family(db_session)

    index_response = client.post(
        "/v1/files/index",
        headers={"X-Dev-User": "u@example.com"},
        json={
            "family_id": family.id,
            "actor": "u@example.com",
            "source_session_id": "files-1",
            "path": "/Notes/Inbox/contractor-estimate.md",
            "name": "contractor-estimate.md",
            "item_type": "document",
            "role": "inbox",
            "title": "Contractor Estimate",
            "summary": "Kitchen remodel estimate and permit notes.",
            "body_text": "Estimate and permit notes for the kitchen remodel.",
            "excerpt_text": "kitchen remodel estimate",
            "content_type": "text/markdown",
            "media_kind": "text",
            "source_date": "2026-03-15",
            "size_bytes": 420,
            "etag": "etag-1",
            "file_id": "file-1",
            "tags": ["projects", "home"],
            "nextcloud_url": "https://nextcloud.example/f/1",
            "related_paths": ["/Notes/Projects/Home/kitchen-remodel.md"],
            "metadata": {"folder": "Inbox"},
        },
    )
    assert index_response.status_code == 201

    search_response = client.post(
        "/v1/files/search",
        headers={"X-Dev-User": "u@example.com"},
        json={
            "family_id": family.id,
            "actor": "u@example.com",
            "query": "kitchen remodel estimate",
            "top_k": 5,
            "preferred_item_types": ["document"],
            "include_content": True,
        },
    )
    assert search_response.status_code == 200
    item = search_response.json()["items"][0]
    assert item["path"] == "/Notes/Inbox/contractor-estimate.md"
    assert item["name"] == "contractor-estimate.md"
    assert item["item_type"] == "document"
    assert item["file_id"] == "file-1"
    assert item["match_reasons"]
