from __future__ import annotations

import app.routers.file_inbox as file_inbox_router
import app.routers.files as files_router
import app.routers.notes as notes_router

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


def test_file_and_note_events_include_high_level_metadata(client, db_session, monkeypatch):
    family = _seed_family(db_session)
    captured: list[dict[str, object]] = []

    monkeypatch.setattr(files_router, "emit_canonical_event", lambda **kwargs: captured.append(kwargs) or "evt-file")
    monkeypatch.setattr(notes_router, "emit_canonical_event", lambda **kwargs: captured.append(kwargs) or "evt-note")

    file_response = client.post(
        "/v1/files/index",
        headers={"X-Dev-User": "u@example.com"},
        json={
            "family_id": family.id,
            "actor": "u@example.com",
            "path": "/Notes/Archive/receipt.pdf",
            "name": "receipt.pdf",
            "item_type": "document",
            "role": "archive",
            "title": "Store Receipt",
            "content_type": "application/pdf",
            "metadata": {"high_level_category": "receipt", "sentiment": "neutral"},
        },
    )
    assert file_response.status_code == 201

    note_response = client.post(
        "/v1/notes/index",
        headers={"X-Dev-User": "u@example.com"},
        json={
            "family_id": family.id,
            "actor": "u@example.com",
            "path": "/Notes/Areas/Church/church-notes.md",
            "item_type": "polished",
            "role": "polished",
            "title": "Church Notes",
            "content_type": "text/markdown",
            "metadata": {"note_type": "church", "high_level_category": "church", "sentiment": "positive"},
        },
    )
    assert note_response.status_code == 201

    assert captured[0]["payload"]["high_level_category"] == "receipt"
    assert captured[0]["payload"]["sentiment"] == "neutral"
    assert captured[1]["payload"]["high_level_category"] == "church"
    assert captured[1]["payload"]["sentiment"] == "positive"


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


def test_file_index_proxies_to_file_api_when_configured(client, db_session, monkeypatch):
    family = _seed_family(db_session)
    captured: dict[str, object] = {}

    monkeypatch.setattr("app.services.file_service_proxy.settings.file_api_base_url", "http://file-api:8000/v1")
    monkeypatch.setattr(
        files_router,
        "proxy_file_request",
        lambda method, path, **kwargs: captured.update({"method": method, "path": path, **kwargs})
        or {
            "doc_id": "doc-1",
            "family_id": family.id,
            "path": "/Notes/Inbox/proxy-test.pdf",
            "item_type": "document",
            "updated_at": "2026-03-24T12:00:00Z",
            "ingestion_status": "indexed",
        },
    )

    response = client.post(
        "/v1/files/index",
        headers={"X-Dev-User": "u@example.com"},
        json={
            "family_id": family.id,
            "actor": "u@example.com",
            "path": "/Notes/Inbox/proxy-test.pdf",
            "name": "proxy-test.pdf",
            "item_type": "document",
            "role": "inbox",
            "title": "Proxy Test",
            "content_type": "application/pdf",
            "metadata": {},
        },
    )

    assert response.status_code == 201
    assert captured["method"] == "POST"
    assert captured["path"] == "/files/index"
    assert captured["headers"] == {"X-Dev-User": "u@example.com"}


def test_process_inbox_proxies_to_file_api_when_configured(client, db_session, monkeypatch):
    family = _seed_family(db_session)
    captured: dict[str, object] = {}

    monkeypatch.setattr("app.services.file_service_proxy.settings.file_api_base_url", "http://file-api:8000/v1")
    monkeypatch.setattr(
        file_inbox_router,
        "proxy_file_request",
        lambda method, path, **kwargs: captured.update({"method": method, "path": path, **kwargs})
        or {
            "status": "completed",
            "processed": 0,
            "indexed": 0,
            "unfiled": 0,
            "skipped_locked": 0,
            "skipped_recent": 0,
            "conflicts": [],
            "results": [],
        },
    )

    response = client.post(
        f"/v1/family/{family.id}/files/process-inbox",
        headers={"X-Dev-User": "u@example.com"},
        json={"include_dashboard_docs": True, "respect_idle_window": True, "source": "home-portal"},
    )

    assert response.status_code == 200
    assert captured["method"] == "POST"
    assert captured["path"] == f"/families/{family.id}/files/process-inbox"
    assert captured["headers"] == {"X-Dev-User": "u@example.com"}
