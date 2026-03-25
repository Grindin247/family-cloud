from __future__ import annotations

from sqlalchemy import select

from app.models.documents import DocumentChunk, IndexJob
from app.schemas.files import FileIndexRequest
from app.services.documents import upsert_file_document
from app.services.jobs import process_pending_jobs


PERSON_ID = "00000000-0000-0000-0000-000000000010"


def _headers() -> dict[str, str]:
    return {"X-Dev-User": "admin@example.com"}


def _file_payload(
    *,
    path: str = "/Notes/Areas/Medical/2025-07-rachel-discharge-summary.pdf",
    file_id: str = "file-1",
    role: str = "filed",
    title: str = "Rachel Discharge Summary",
    summary: str = "Rachel's hospital discharge papers from last summer.",
    body_text: str = "Rachel's July hospital discharge papers with recovery instructions and follow-up notes.",
) -> dict[str, object]:
    return {
        "family_id": 2,
        "actor": "admin@example.com",
        "owner_person_id": None,
        "source_agent_id": "manual-test",
        "source_session_id": "file-test-session",
        "path": path,
        "name": path.rsplit("/", 1)[-1],
        "item_type": "document",
        "role": role,
        "title": title,
        "summary": summary,
        "body_text": body_text,
        "excerpt_text": summary,
        "content_type": "application/pdf",
        "media_kind": "text",
        "source_date": "2025-07-18",
        "size_bytes": 24576,
        "etag": f"etag-{file_id}",
        "file_id": file_id,
        "tags": ["medical", "insurance"],
        "nextcloud_url": f"https://nextcloud.example/f/{file_id}",
        "related_paths": ["/Notes/Areas/Medical/follow-up-appointments.md"],
        "source_refs": [{"label": title, "path": path, "locator_type": "path", "locator_value": path}],
        "metadata": {"destination_folder": "Areas", "high_level_category": "medical"},
    }


def _note_payload() -> dict[str, object]:
    path = "/Notes/Areas/Church/2026-02-bible-study-plan.md"
    return {
        "family_id": 2,
        "actor": "admin@example.com",
        "owner_person_id": None,
        "source_agent_id": "manual-test",
        "source_session_id": "note-test-session",
        "path": path,
        "name": path.rsplit("/", 1)[-1],
        "item_type": "polished",
        "role": "polished",
        "title": "February Bible Study Plan",
        "summary": "The Bible study plan we used in February.",
        "body_text": "Week-by-week February Bible study plan with prayer focus and scripture readings.",
        "excerpt_text": "February Bible study plan",
        "content_type": "text/markdown",
        "source_date": "2026-02-01",
        "size_bytes": 2048,
        "etag": "etag-note-1",
        "file_id": "note-file-1",
        "tags": ["church", "study"],
        "nextcloud_url": "https://nextcloud.example/f/note-file-1",
        "raw_note_url": "https://nextcloud.example/raw/note-file-1",
        "related_paths": ["/Notes/Archive/Raw/Church/2026-02-bible-study-plan-raw.md"],
        "source_refs": [{"label": "February Bible Study Plan", "path": path, "locator_type": "path", "locator_value": path}],
        "metadata": {"note_type": "church"},
    }


def test_file_note_index_search_and_unified_search(client) -> None:
    file_response = client.post("/v1/files/index", headers=_headers(), json=_file_payload())
    assert file_response.status_code == 201
    assert file_response.json()["ingestion_status"] == "indexed"

    note_response = client.post("/v1/notes/index", headers=_headers(), json=_note_payload())
    assert note_response.status_code == 201
    assert note_response.json()["ingestion_status"] == "indexed"

    file_search = client.post(
        "/v1/files/search",
        headers=_headers(),
        json={
            "family_id": 2,
            "actor": "admin@example.com",
            "query": "Rachel hospital discharge papers July",
            "top_k": 5,
            "preferred_item_types": ["document"],
            "include_content": True,
        },
    )
    assert file_search.status_code == 200
    file_item = file_search.json()["items"][0]
    assert file_item["path"] == "/Notes/Areas/Medical/2025-07-rachel-discharge-summary.pdf"
    assert file_item["owner_person_id"] == PERSON_ID
    assert file_item["match_reasons"]

    note_search = client.post(
        "/v1/notes/search",
        headers=_headers(),
        json={
            "family_id": 2,
            "actor": "admin@example.com",
            "query": "Bible study plan February",
            "top_k": 5,
            "query_tags": ["church"],
            "include_content": True,
        },
    )
    assert note_search.status_code == 200
    note_item = note_search.json()["items"][0]
    assert note_item["path"] == "/Notes/Areas/Church/2026-02-bible-study-plan.md"
    assert note_item["raw_note_url"] == "https://nextcloud.example/raw/note-file-1"

    unified = client.post(
        "/v1/search",
        headers=_headers(),
        json={
            "family_id": 2,
            "actor": "admin@example.com",
            "query": "Bible study plan February",
            "top_k": 5,
            "include_content": True,
        },
    )
    assert unified.status_code == 200
    top = unified.json()["items"][0]
    assert top["document_kind"] == "note"
    assert top["path"] == "/Notes/Areas/Church/2026-02-bible-study-plan.md"


def test_upsert_preserves_doc_id_on_move_and_skips_reembedding(db_session, monkeypatch) -> None:
    embed_calls: list[list[str]] = []

    def _fake_embed_texts(texts, *, is_query=False, dim=None):
        embed_calls.append(list(texts))
        return [None for _ in texts]

    monkeypatch.setattr("app.services.documents._supports_vector_search", lambda db: True)
    monkeypatch.setattr("app.services.documents.embed_texts", _fake_embed_texts)

    first = upsert_file_document(
        db_session,
        payload=FileIndexRequest.model_validate(_file_payload(path="/Notes/Inbox/van-insurance.pdf", file_id="file-55", role="inbox")),
    )
    db_session.commit()
    db_session.refresh(first)

    second = upsert_file_document(
        db_session,
        payload=FileIndexRequest.model_validate(
            _file_payload(path="/Notes/Areas/Insurance/van-insurance.pdf", file_id="file-55", role="filed")
        ),
    )
    db_session.commit()
    db_session.refresh(second)

    assert str(second.doc_id) == str(first.doc_id)
    assert len(embed_calls) == 1

    chunk = db_session.execute(select(DocumentChunk).where(DocumentChunk.doc_id == second.doc_id)).scalar_one()
    assert chunk.source_ref_jsonb["path"] == "/Notes/Areas/Insurance/van-insurance.pdf"


def test_embedding_failure_stays_searchable_and_queues_reindex(client, db_session, monkeypatch) -> None:
    monkeypatch.setattr("app.services.documents._supports_vector_search", lambda db: True)

    def _failing_embed_texts(*args, **kwargs):
        raise RuntimeError("embedder unavailable")

    monkeypatch.setattr("app.services.documents.embed_texts", _failing_embed_texts)

    response = client.post("/v1/files/index", headers=_headers(), json=_file_payload(file_id="file-embed-fail"))
    assert response.status_code == 201
    assert response.json()["ingestion_status"] == "indexed_lexical_only"

    jobs = db_session.execute(select(IndexJob).where(IndexJob.job_type == "reindex_document")).scalars().all()
    assert len(jobs) == 1
    assert jobs[0].status == "pending"

    file_search = client.post(
        "/v1/files/search",
        headers=_headers(),
        json={
            "family_id": 2,
            "actor": "admin@example.com",
            "query": "Rachel hospital discharge papers July",
            "top_k": 5,
            "include_content": True,
        },
    )
    assert file_search.status_code == 200
    assert file_search.json()["items"][0]["path"] == "/Notes/Areas/Medical/2025-07-rachel-discharge-summary.pdf"

    monkeypatch.setattr("app.services.documents.embed_texts", lambda texts, **kwargs: [None for _ in texts])
    result = process_pending_jobs(db_session, limit=10)
    db_session.commit()

    assert result["processed"] == 1
    job = db_session.execute(select(IndexJob).where(IndexJob.job_type == "reindex_document")).scalar_one()
    assert job.status == "completed"
    assert job.result_jsonb["reindexed"] is True


def test_search_is_family_wide_by_default_and_can_filter_owner(client) -> None:
    other_owner = "00000000-0000-0000-0000-000000000099"
    payload = _file_payload(
        path="/Notes/Areas/Medical/2025-07-rachel-discharge-summary.pdf",
        file_id="file-rachel",
        title="Rachel Discharge Summary",
        summary="Rachel's hospital discharge papers from last summer.",
    )
    payload["owner_person_id"] = other_owner

    indexed = client.post("/v1/files/index", headers=_headers(), json=payload)
    assert indexed.status_code == 201

    family_wide = client.post(
        "/v1/files/search",
        headers=_headers(),
        json={
            "family_id": 2,
            "actor": "admin@example.com",
            "query": "Rachel hospital discharge papers",
            "top_k": 5,
            "include_content": True,
        },
    )
    assert family_wide.status_code == 200
    assert family_wide.json()["items"][0]["owner_person_id"] == other_owner

    filtered = client.post(
        "/v1/files/search",
        headers=_headers(),
        json={
            "family_id": 2,
            "actor": "admin@example.com",
            "query": "Rachel hospital discharge papers",
            "top_k": 5,
            "include_content": True,
            "owner_person_id": other_owner,
        },
    )
    assert filtered.status_code == 200
    assert filtered.json()["items"][0]["path"] == "/Notes/Areas/Medical/2025-07-rachel-discharge-summary.pdf"


def test_followup_job_endpoint_and_process_inbox_route(client, db_session, monkeypatch) -> None:
    created = client.post(
        "/v1/families/2/jobs/followups",
        headers=_headers(),
        json={
            "actor": "admin@example.com",
            "job_type": "create_question",
            "dedupe_key": "followup-1",
            "payload": {
                "domain": "file",
                "source_agent": "FileAgent",
                "topic": "folder-choice",
                "summary": "Need help placing a file.",
                "prompt": "Where should this file live?",
            },
        },
    )
    assert created.status_code == 201

    duplicate = client.post(
        "/v1/families/2/jobs/followups",
        headers=_headers(),
        json={
            "actor": "admin@example.com",
            "job_type": "create_question",
            "dedupe_key": "followup-1",
            "payload": {
                "domain": "file",
                "source_agent": "FileAgent",
                "topic": "folder-choice",
                "summary": "Need help placing a file.",
                "prompt": "Where should this file live?",
            },
        },
    )
    assert duplicate.status_code == 201
    assert duplicate.json()["job_id"] == created.json()["job_id"]

    jobs = db_session.execute(select(IndexJob).where(IndexJob.job_type == "create_question")).scalars().all()
    assert len(jobs) == 1

    captured: dict[str, object] = {}

    async def _fake_process_inbox_async(**kwargs):
        captured.update(kwargs)
        return {
            "status": "completed",
            "processed": 1,
            "indexed": 1,
            "unfiled": 0,
            "skipped_locked": 0,
            "skipped_recent": 0,
            "conflicts": [],
            "results": [
                {
                    "source_path": "/Notes/Inbox/scan.pdf",
                    "destination_path": "/Notes/Areas/Medical/scan.pdf",
                    "title": "Scan",
                    "folder": "Areas",
                    "item_type": "document",
                    "confidence": 0.91,
                    "indexed": True,
                    "unreadable": False,
                    "reason": "keyword-match",
                    "nextcloud_url": "https://nextcloud.example/f/scan",
                }
            ],
        }

    monkeypatch.setattr("app.routers.files.process_inbox_async", _fake_process_inbox_async)

    response = client.post(
        "/v1/families/2/files/process-inbox",
        headers=_headers(),
        json={"include_dashboard_docs": True, "respect_idle_window": True, "source": "home-portal"},
    )

    assert response.status_code == 200
    assert response.json()["processed"] == 1
    assert captured["actor"] == "admin@example.com"
    assert captured["decision_api_base_url"] == "http://file-api:8000/v1"
    assert captured["dashboard_idle_minutes"] == 10
    assert captured["confidence_threshold"] == 0.70
