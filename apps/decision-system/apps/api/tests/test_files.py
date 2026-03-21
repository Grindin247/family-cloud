from __future__ import annotations

import app.routers.file_inbox as file_inbox_router

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


def test_process_inbox_endpoint_returns_summary_shape(client, db_session, monkeypatch):
    family = _seed_family(db_session)
    captured: dict[str, object] = {}

    async def _fake_process_inbox_async(**kwargs):
        captured.update(kwargs)
        return {
            "status": "completed",
            "processed": 2,
            "indexed": 2,
            "unfiled": 0,
            "skipped_locked": 1,
            "skipped_recent": 1,
            "conflicts": [],
            "results": [
                {
                    "source_path": "/Notes/Inbox/Family Cloud Doc 2026-03-20 10-00-00.md",
                    "destination_path": "/Notes/Projects/2026-03-20_100000_kitchen-remodel-notes.md",
                    "title": "Kitchen Remodel Notes",
                    "folder": "Projects",
                    "item_type": "note",
                    "confidence": 0.93,
                    "indexed": True,
                    "unreadable": False,
                    "reason": "dashboard-doc:keyword-score:projects=2",
                    "nextcloud_url": "https://nextcloud.example/apps/files/files/Notes/Projects/2026-03-20_100000_kitchen-remodel-notes.md",
                }
            ],
        }

    monkeypatch.setattr(file_inbox_router, "process_inbox_async", _fake_process_inbox_async)

    response = client.post(
        f"/v1/family/{family.id}/files/process-inbox",
        headers={"X-Dev-User": "u@example.com"},
        json={
            "include_dashboard_docs": True,
            "respect_idle_window": True,
            "source": "home-portal",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["processed"] == 2
    assert body["indexed"] == 2
    assert body["skipped_locked"] == 1
    assert body["skipped_recent"] == 1
    assert body["results"][0]["title"] == "Kitchen Remodel Notes"
    assert body["results"][0]["nextcloud_url"].startswith("https://nextcloud.example/")
    assert captured["actor"] == "u@example.com"
    assert captured["family_id"] == family.id
    assert captured["include_dashboard_docs"] is True
