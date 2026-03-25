from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.common import file_inbox


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


@dataclass
class _Candidate:
    path: str
    name: str
    size: int
    content_type: str
    last_modified: str | None
    etag: str | None = None
    file_id: str | None = None
    lock_owner: str | None = None
    source_kind: str = "ready-tag"


class _DiscoveryClient:
    def __init__(self, *, ready: list[_Candidate], inbox_entries: list[dict[str, object]]) -> None:
        self._ready = ready
        self._inbox_entries = inbox_entries

    async def list_ready_files(self, scope: str, tag_name: str) -> list[_Candidate]:
        assert scope == "/Notes/Inbox"
        assert tag_name == "ready"
        return list(self._ready)

    async def list_directory(self, path: str) -> list[dict[str, object]]:
        assert path == "/Notes/Inbox"
        return list(self._inbox_entries)


class _FailingReadyDiscoveryClient(_DiscoveryClient):
    async def list_ready_files(self, scope: str, tag_name: str) -> list[_Candidate]:
        raise RuntimeError("ready-tag lookup failed")


class _ProcessClient:
    def __init__(self) -> None:
        now = datetime.now(UTC) - timedelta(minutes=20)
        self.ready = [
            file_inbox.InboxCandidate(
                path="/Notes/Inbox/scan.pdf",
                name="scan.pdf",
                size=128,
                content_type="application/pdf",
                last_modified=_iso(now),
                etag="etag-1",
                file_id="file-1",
            )
        ]
        self.inbox_entries = [
            {
                "path": "/Notes/Inbox/scan.pdf",
                "name": "scan.pdf",
                "size": 128,
                "content_type": "application/pdf",
                "last_modified": _iso(now),
                "etag": "etag-1",
                "file_id": "file-1",
                "is_directory": False,
                "lock_owner": "",
            }
        ]
        self.moved: list[tuple[str, str]] = []
        self.tag_removals: list[tuple[str | None, str]] = []

    async def __aenter__(self) -> _ProcessClient:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def list_ready_files(self, scope: str, tag_name: str) -> list[file_inbox.InboxCandidate]:
        assert scope == "/Notes/Inbox"
        assert tag_name == "ready"
        return list(self.ready)

    async def list_directory(self, path: str) -> list[dict[str, object]]:
        if path == "/Notes/Inbox":
            return list(self.inbox_entries)
        return []

    async def create_directory(self, path: str) -> None:
        return None

    async def read_file(self, path: str) -> dict[str, object]:
        assert path == "/Notes/Inbox/scan.pdf"
        return {"path": path, "content_type": "application/pdf"}

    async def read_raw_file(self, path: str) -> dict[str, object]:
        assert path == "/Notes/Inbox/scan.pdf"
        return {"path": path, "content": "", "content_type": "application/pdf", "encoding": "base64"}

    async def move_resource(self, source_path: str, destination_path: str) -> None:
        self.moved.append((source_path, destination_path))

    async def write_file(self, path: str, content: str, *, content_type: str | None = None) -> None:
        raise AssertionError("generic unreadable file should not be rewritten")

    async def remove_tag_from_file(self, file_id: str | None, tag_name: str) -> None:
        self.tag_removals.append((file_id, tag_name))


class _ReadableProcessClient(_ProcessClient):
    def __init__(self) -> None:
        super().__init__()
        now = datetime.now(UTC) - timedelta(minutes=20)
        self.ready = [
            file_inbox.InboxCandidate(
                path="/Notes/Inbox/Family Cloud Doc 2026-03-20 10-00-00.md",
                name="Family Cloud Doc 2026-03-20 10-00-00.md",
                size=256,
                content_type="text/markdown",
                last_modified=_iso(now),
                etag="etag-readable",
                file_id="file-readable",
                source_kind="dashboard-doc",
            )
        ]
        self.inbox_entries = [
            {
                "path": "/Notes/Inbox/Family Cloud Doc 2026-03-20 10-00-00.md",
                "name": "Family Cloud Doc 2026-03-20 10-00-00.md",
                "size": 256,
                "content_type": "text/markdown",
                "last_modified": _iso(now),
                "etag": "etag-readable",
                "file_id": "file-readable",
                "is_directory": False,
                "lock_owner": "",
            }
        ]
        self.writes: list[tuple[str, str, str | None]] = []

    async def read_file(self, path: str) -> dict[str, object]:
        assert path == "/Notes/Inbox/Family Cloud Doc 2026-03-20 10-00-00.md"
        return {
            "path": path,
            "content_type": "text/markdown",
            "content": "Quick notes from the kitchen remodel planning meeting.\nWe need to finalize cabinet samples.\nCall the contractor by Friday.\nDo we need a permit for moving the sink?",
        }

    async def read_raw_file(self, path: str) -> dict[str, object]:
        raise AssertionError("readable markdown should not require raw fallback")

    async def write_file(self, path: str, content: str, *, content_type: str | None = None) -> None:
        self.writes.append((path, content, content_type))


def test_discover_candidates_includes_idle_dashboard_docs_and_skips_locked_or_recent() -> None:
    now = datetime.now(UTC)
    client = _DiscoveryClient(
        ready=[],
        inbox_entries=[
            {
                "path": "/Notes/Inbox/Family Cloud Doc 2026-03-20 10-00-00.md",
                "name": "Family Cloud Doc 2026-03-20 10-00-00.md",
                "size": 240,
                "content_type": "text/markdown",
                "last_modified": _iso(now - timedelta(minutes=30)),
                "is_directory": False,
                "lock_owner": "",
            },
            {
                "path": "/Notes/Inbox/Family Cloud Doc 2026-03-20 10-05-00.md",
                "name": "Family Cloud Doc 2026-03-20 10-05-00.md",
                "size": 128,
                "content_type": "text/markdown",
                "last_modified": _iso(now - timedelta(minutes=30)),
                "is_directory": False,
                "lock_owner": "Someone Else",
            },
            {
                "path": "/Notes/Inbox/Family Cloud Doc 2026-03-20 10-09-00.md",
                "name": "Family Cloud Doc 2026-03-20 10-09-00.md",
                "size": 128,
                "content_type": "text/markdown",
                "last_modified": _iso(now - timedelta(minutes=2)),
                "is_directory": False,
                "lock_owner": "",
            },
        ],
    )

    candidates, skipped_locked, skipped_recent = asyncio.run(
        file_inbox.discover_candidates(
            client,
            ready_tag="ready",
            include_dashboard_docs=True,
            idle_minutes=10,
        )
    )

    assert [candidate.path for candidate in candidates] == ["/Notes/Inbox/Family Cloud Doc 2026-03-20 10-00-00.md"]
    assert candidates[0].source_kind == "dashboard-doc"
    assert skipped_locked == 1
    assert skipped_recent == 1


def test_discover_candidates_drops_locked_ready_files_when_lock_metadata_exists() -> None:
    now = datetime.now(UTC)
    client = _DiscoveryClient(
        ready=[
            _Candidate(
                path="/Notes/Inbox/receipt.pdf",
                name="receipt.pdf",
                size=512,
                content_type="application/pdf",
                last_modified=_iso(now - timedelta(minutes=45)),
                file_id="file-2",
            )
        ],
        inbox_entries=[
            {
                "path": "/Notes/Inbox/receipt.pdf",
                "name": "receipt.pdf",
                "size": 512,
                "content_type": "application/pdf",
                "last_modified": _iso(now - timedelta(minutes=45)),
                "is_directory": False,
                "lock_owner": "Editing User",
            }
        ],
    )

    candidates, skipped_locked, skipped_recent = asyncio.run(
        file_inbox.discover_candidates(
            client,
            ready_tag="ready",
            include_dashboard_docs=False,
            idle_minutes=10,
        )
    )

    assert candidates == []
    assert skipped_locked == 1
    assert skipped_recent == 0


def test_discover_candidates_includes_closed_unready_files_for_closed_inbox_mode() -> None:
    now = datetime.now(UTC)
    client = _DiscoveryClient(
        ready=[
            _Candidate(
                path="/Notes/Inbox/ready.pdf",
                name="ready.pdf",
                size=512,
                content_type="application/pdf",
                last_modified=_iso(now - timedelta(minutes=45)),
                file_id="file-ready",
            )
        ],
        inbox_entries=[
            {
                "path": "/Notes/Inbox/ready.pdf",
                "name": "ready.pdf",
                "size": 512,
                "content_type": "application/pdf",
                "last_modified": _iso(now - timedelta(minutes=45)),
                "etag": "etag-ready",
                "file_id": "file-ready",
                "is_directory": False,
                "lock_owner": "",
            },
            {
                "path": "/Notes/Inbox/untagged.pdf",
                "name": "untagged.pdf",
                "size": 256,
                "content_type": "application/pdf",
                "last_modified": _iso(now - timedelta(minutes=45)),
                "etag": "etag-untagged",
                "file_id": "file-untagged",
                "is_directory": False,
                "lock_owner": "",
            },
            {
                "path": "/Notes/Inbox/locked.pdf",
                "name": "locked.pdf",
                "size": 256,
                "content_type": "application/pdf",
                "last_modified": _iso(now - timedelta(minutes=45)),
                "etag": "etag-locked",
                "file_id": "file-locked",
                "is_directory": False,
                "lock_owner": "Editing User",
            },
        ],
    )

    candidates, skipped_locked, skipped_recent = asyncio.run(
        file_inbox.discover_candidates(
            client,
            ready_tag="ready",
            include_dashboard_docs=True,
            idle_minutes=10,
            candidate_mode="closed-inbox",
        )
    )

    assert [candidate.path for candidate in candidates] == [
        "/Notes/Inbox/ready.pdf",
        "/Notes/Inbox/untagged.pdf",
    ]
    assert candidates[0].source_kind == "ready-tag"
    assert candidates[1].source_kind == "closed-inbox"
    assert skipped_locked == 1
    assert skipped_recent == 0


def test_discover_candidates_refreshes_ready_candidate_metadata_from_directory_listing() -> None:
    now = datetime.now(UTC)
    client = _DiscoveryClient(
        ready=[
            _Candidate(
                path="/Notes/Inbox/img.pdf",
                name="img.pdf",
                size=0,
                content_type="application/octet-stream",
                last_modified=None,
                file_id="file-3",
            )
        ],
        inbox_entries=[
            {
                "path": "/Notes/Inbox/img.pdf",
                "name": "img.pdf",
                "size": 88381,
                "content_type": "application/pdf",
                "last_modified": _iso(now - timedelta(minutes=30)),
                "etag": "etag-3",
                "file_id": "file-3",
                "is_directory": False,
                "lock_owner": "",
            }
        ],
    )

    candidates, _, _ = asyncio.run(
        file_inbox.discover_candidates(
            client,
            ready_tag="ready",
            include_dashboard_docs=False,
            idle_minutes=10,
        )
    )

    assert len(candidates) == 1
    assert candidates[0].size == 88381
    assert candidates[0].content_type == "application/pdf"
    assert candidates[0].etag == "etag-3"


def test_discover_candidates_still_processes_dashboard_docs_when_ready_lookup_fails() -> None:
    now = datetime.now(UTC)
    client = _FailingReadyDiscoveryClient(
        ready=[],
        inbox_entries=[
            {
                "path": "/Notes/Inbox/Family Cloud Doc 2026-03-20 10-00-00.md",
                "name": "Family Cloud Doc 2026-03-20 10-00-00.md",
                "size": 240,
                "content_type": "text/markdown",
                "last_modified": _iso(now - timedelta(minutes=30)),
                "is_directory": False,
                "lock_owner": "",
            }
        ],
    )

    candidates, skipped_locked, skipped_recent = asyncio.run(
        file_inbox.discover_candidates(
            client,
            ready_tag="ready",
            include_dashboard_docs=True,
            idle_minutes=10,
        )
    )

    assert [candidate.path for candidate in candidates] == ["/Notes/Inbox/Family Cloud Doc 2026-03-20 10-00-00.md"]
    assert skipped_locked == 0
    assert skipped_recent == 0


def test_build_structured_note_markdown_appends_raw_capture_and_sections() -> None:
    content = file_inbox._build_structured_note_markdown(
        title="Kitchen Remodel Notes",
        summary="The note captures planning decisions for the kitchen remodel and the next coordination step.",
        key_insights=["Cabinet samples still need to be finalized."],
        actions=["Call the contractor."],
        open_questions=["What is the permit cost?"],
        raw_note_content="Plan the kitchen remodel this month.\nTODO: call the contractor.\nWhat is the permit cost?",
    )

    assert content.startswith("# Kitchen Remodel Notes\n\n## Summary\n")
    assert "\n## Key Insights\n" in content
    assert "\n## Actions\n" in content
    assert "\n## Open Questions\n" in content
    assert "\n## Raw Note Content\n" in content
    assert content.rstrip().endswith("What is the permit cost?")


def test_parse_file_agent_result_normalizes_semantic_fields() -> None:
    decision = file_inbox._parse_file_agent_result(
        {
            "folder": "Projects",
            "subfolder_path": "Home/Kitchen Remodel",
            "title": "Kitchen Remodel Planning Notes",
            "filename_slug": "kitchen-remodel-plan",
            "summary": "This note captures the remodel planning conversation and the next coordination steps.",
            "key_insights": ["Cabinet samples still need to be finalized."],
            "actions": ["Call the contractor by Friday."],
            "open_questions": ["Do we need a permit for moving the sink?"],
            "rewritten_markdown": "# Kitchen Remodel Planning Notes\n",
            "confidence": 0.88,
            "reason": "project-planning-note",
            "high_level_category": "project",
            "sentiment": "neutral",
        },
        "Raw kitchen remodel text",
    )

    assert decision.folder == "Projects"
    assert decision.subfolder_path == "Home/Kitchen Remodel"
    assert decision.filename_slug == "kitchen-remodel-plan"
    assert decision.rewritten_markdown == "# Kitchen Remodel Planning Notes\n"
    assert decision.summary.startswith("This note captures")
    assert decision.actions == ["Call the contractor by Friday."]
    assert decision.high_level_category == "project"
    assert decision.sentiment == "neutral"


def test_infer_file_item_type_keeps_ocr_images_as_images() -> None:
    assert file_inbox.infer_file_item_type("image/png", ".png", "Receipt total 18.42") == "image"


def test_destination_directory_routes_church_area_notes_into_church_subfolder() -> None:
    assert file_inbox._destination_directory(folder="Areas", high_level_category="church") == "/Notes/Areas/Church"
    assert (
        file_inbox._destination_directory(
            folder="Areas",
            high_level_category="school",
            subfolder_path="School/Assignments/Valerie",
        )
        == "/Notes/Areas/School/Assignments/Valerie"
    )
    assert file_inbox._destination_directory(folder="Resources", high_level_category="unknown") == "/Notes/Resources/General"


def test_destination_directory_limits_file_agent_subfolder_depth() -> None:
    assert (
        file_inbox._destination_directory(
            folder="Areas",
            high_level_category="school",
            subfolder_path="Areas/School/Assignments/Valerie/Fourth Grade",
        )
        == "/Notes/Areas/School/Assignments/Valerie"
    )


def test_decode_read_payload_rejects_parser_placeholder_text() -> None:
    readable_text, _, content_type, reliability, page_image_paths, observed_size = file_inbox._decode_read_payload(
        {
            "content": "Document could not be parsed. Base64 content: abc123",
            "content_type": "application/pdf",
        },
        ".pdf",
    )

    assert readable_text is None
    assert content_type == "application/pdf"
    assert reliability == "low"
    assert page_image_paths == []
    assert observed_size is None


def test_decode_read_payload_rejects_pdf_image_placeholder_markdown() -> None:
    readable_text, _, content_type, reliability, page_image_paths, observed_size = file_inbox._decode_read_payload(
        {
            "content": "![](/tmp/pdf-images/_Notes_Inbox_img20260314_11081111.pdf/pdf-0-full.png)",
            "content_type": "application/pdf",
            "size": 88381,
        },
        ".pdf",
    )

    assert readable_text is None
    assert content_type == "application/pdf"
    assert reliability == "low"
    assert page_image_paths == ["/tmp/pdf-images/_Notes_Inbox_img20260314_11081111.pdf/pdf-0-full.png"]
    assert observed_size == 88381


def test_sample_page_image_paths_uses_first_middle_last() -> None:
    paths = [f"/tmp/pdf-images/doc/pdf-{idx}-full.png" for idx in range(4)]

    assert file_inbox._sample_page_image_paths(paths) == [
        "/tmp/pdf-images/doc/pdf-0-full.png",
        "/tmp/pdf-images/doc/pdf-2-full.png",
        "/tmp/pdf-images/doc/pdf-3-full.png",
    ]


def test_stage_page_image_paths_copies_existing_samples(tmp_path, monkeypatch) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    first = source_dir / "page-0.png"
    second = source_dir / "page-1.png"
    first.write_bytes(b"one")
    second.write_bytes(b"two")
    monkeypatch.setattr(file_inbox, "FILE_AGENT_IMAGE_STAGING_DIR", tmp_path / "staged")

    staged = file_inbox._stage_page_image_paths([str(first), str(second)], source_path="/Notes/Inbox/doc.pdf")

    assert len(staged) == 2
    assert Path(staged[0]).read_bytes() == b"one"
    assert Path(staged[1]).read_bytes() == b"two"


def test_extract_json_candidate_text_skips_narrative_and_parses_embedded_object() -> None:
    decoded = file_inbox._extract_json_candidate_text(
        'I checked the file read-only. {"folder":"Areas","title":"Church Notes","filename_slug":"church-notes"}'
    )

    assert decoded == {
        "folder": "Areas",
        "title": "Church Notes",
        "filename_slug": "church-notes",
    }


def test_invoke_file_agent_json_uses_json_payload_even_when_first_payload_is_narrative(monkeypatch) -> None:
    seen: dict[str, object] = {}

    class _Completed:
        returncode = 0
        stderr = ""
        stdout = json.dumps(
            {
                "result": {
                    "payloads": [
                        {"text": "I am checking the file itself read-only."},
                        {"text": '{"folder":"Areas","title":"Church Notes","filename_slug":"church-notes"}'},
                    ]
                }
            }
        )

    def _fake_run(args, **kwargs):
        seen["args"] = args
        return _Completed()

    monkeypatch.setenv("OPENCLAW_BIN", "/custom/bin/openclaw")
    monkeypatch.setattr(file_inbox.subprocess, "run", _fake_run)

    assert file_inbox._invoke_file_agent_json(prompt="prompt", timeout_seconds=5) == {
        "folder": "Areas",
        "title": "Church Notes",
        "filename_slug": "church-notes",
    }
    assert seen["args"][0] == "/custom/bin/openclaw"


def test_process_inbox_falls_back_to_unfiled_for_low_confidence_files(monkeypatch) -> None:
    fake_client = _ProcessClient()
    queued: list[dict[str, object]] = []

    monkeypatch.setattr(file_inbox, "McpNextcloudClient", lambda url: fake_client)
    monkeypatch.setattr(file_inbox, "_index_document", lambda **kwargs: False)
    monkeypatch.setattr(file_inbox, "_create_file_question", lambda **kwargs: queued.append(kwargs))
    monkeypatch.setattr(
        file_inbox,
        "synthesize_note_with_file_agent",
        lambda **kwargs: file_inbox.FileAgentInboxDecision(
            folder="Projects",
            subfolder_path="Projects/Home Remodel",
            title="Project Scan",
            filename_slug="project-scan",
            summary="A scanned file related to a project.",
            key_insights=["Looks project-related."],
            actions=[],
            open_questions=[],
            rewritten_markdown="",
            high_level_category="project",
            sentiment="unknown",
            confidence=0.4,
            reason="low-confidence-project-scan",
        ),
    )

    summary = asyncio.run(
        file_inbox.process_inbox_async(
            mcp_url="http://nextcloud-mcp:8000/mcp",
            ready_tag="ready",
            decision_api_base_url="http://decision-api:8000/v1",
            actor="u@example.com",
            family_id=2,
            nextcloud_base_url="https://nextcloud.example",
        )
    )

    assert summary["processed"] == 1
    assert summary["unfiled"] == 1
    assert summary["results"][0]["folder"] == "Unfiled"
    assert summary["results"][0]["item_type"] == "other"
    assert summary["results"][0]["confidence"] == 0.4
    assert fake_client.moved[0][0] == "/Notes/Inbox/scan.pdf"
    assert fake_client.moved[0][1].startswith("/Notes/Unfiled/")
    assert fake_client.tag_removals == [("file-1", "ready")]
    assert len(queued) == 1


def test_process_inbox_respects_max_candidates_and_defers_the_rest(monkeypatch) -> None:
    fake_client = _ProcessClient()
    now = datetime.now(UTC) - timedelta(minutes=20)
    fake_client.ready = [
        file_inbox.InboxCandidate(
            path="/Notes/Inbox/newer.pdf",
            name="newer.pdf",
            size=128,
            content_type="application/pdf",
            last_modified=_iso(now + timedelta(minutes=5)),
            etag="etag-newer",
            file_id="file-newer",
        ),
        file_inbox.InboxCandidate(
            path="/Notes/Inbox/older.pdf",
            name="older.pdf",
            size=128,
            content_type="application/pdf",
            last_modified=_iso(now),
            etag="etag-older",
            file_id="file-older",
        ),
    ]
    fake_client.inbox_entries = [
        {
            "path": "/Notes/Inbox/newer.pdf",
            "name": "newer.pdf",
            "size": 128,
            "content_type": "application/pdf",
            "last_modified": _iso(now + timedelta(minutes=5)),
            "etag": "etag-newer",
            "file_id": "file-newer",
            "is_directory": False,
            "lock_owner": "",
        },
        {
            "path": "/Notes/Inbox/older.pdf",
            "name": "older.pdf",
            "size": 128,
            "content_type": "application/pdf",
            "last_modified": _iso(now),
            "etag": "etag-older",
            "file_id": "file-older",
            "is_directory": False,
            "lock_owner": "",
        },
    ]

    async def _read_file(path: str) -> dict[str, object]:
        return {"path": path, "content_type": "application/pdf"}

    async def _read_raw_file(path: str) -> dict[str, object]:
        return {"path": path, "content": "", "content_type": "application/pdf", "encoding": "base64"}

    fake_client.read_file = _read_file  # type: ignore[method-assign]
    fake_client.read_raw_file = _read_raw_file  # type: ignore[method-assign]

    monkeypatch.setattr(file_inbox, "McpNextcloudClient", lambda url: fake_client)
    monkeypatch.setattr(file_inbox, "_index_document", lambda **kwargs: False)
    monkeypatch.setattr(
        file_inbox,
        "synthesize_note_with_file_agent",
        lambda **kwargs: file_inbox.FileAgentInboxDecision(
            folder="Areas",
            subfolder_path="School/Assignments",
            title="School Packet",
            filename_slug="school-packet",
            summary="A school packet.",
            key_insights=[],
            actions=[],
            open_questions=[],
            rewritten_markdown="",
            high_level_category="school",
            sentiment="neutral",
            confidence=0.95,
            reason="school-packet",
        ),
    )

    summary = asyncio.run(
        file_inbox.process_inbox_async(
            mcp_url="http://nextcloud-mcp:8000/mcp",
            ready_tag="ready",
            decision_api_base_url="http://decision-api:8000/v1",
            actor="u@example.com",
            family_id=2,
            nextcloud_base_url="https://nextcloud.example",
            max_candidates=1,
        )
    )

    assert summary["discovered"] == 2
    assert summary["deferred"] == 1
    assert summary["processed"] == 1
    assert fake_client.moved[0][0] == "/Notes/Inbox/older.pdf"
    assert fake_client.tag_removals == [("file-older", "ready")]


def test_process_inbox_uses_file_agent_for_readable_notes(monkeypatch) -> None:
    fake_client = _ReadableProcessClient()

    monkeypatch.setattr(file_inbox, "McpNextcloudClient", lambda url: fake_client)
    monkeypatch.setattr(file_inbox, "_index_document", lambda **kwargs: True)
    monkeypatch.setattr(
        file_inbox,
        "synthesize_note_with_file_agent",
        lambda **kwargs: file_inbox.FileAgentInboxDecision(
            folder="Projects",
            subfolder_path="Home/Kitchen Remodel",
            title="Kitchen Remodel Planning Notes",
            filename_slug="kitchen-remodel-planning",
            summary="This note captures the remodel planning discussion and highlights the next coordination steps.",
            key_insights=["Cabinet samples still need a final decision."],
            actions=["Call the contractor by Friday."],
            open_questions=["Do we need a permit for moving the sink?"],
            rewritten_markdown=file_inbox._build_structured_note_markdown(
                title="Kitchen Remodel Planning Notes",
                summary="This note captures the remodel planning discussion and highlights the next coordination steps.",
                key_insights=["Cabinet samples still need a final decision."],
                actions=["Call the contractor by Friday."],
                open_questions=["Do we need a permit for moving the sink?"],
                raw_note_content="raw note",
            ),
            high_level_category="project",
            sentiment="neutral",
            confidence=0.91,
            reason="project-planning-note",
        ),
    )

    summary = asyncio.run(
        file_inbox.process_inbox_async(
            mcp_url="http://nextcloud-mcp:8000/mcp",
            ready_tag="ready",
            decision_api_base_url="http://decision-api:8000/v1",
            actor="u@example.com",
            family_id=2,
            nextcloud_base_url="https://nextcloud.example",
        )
    )

    assert summary["processed"] == 1
    assert summary["unfiled"] == 0
    assert summary["results"][0]["folder"] == "Projects"
    assert fake_client.moved[0][1].startswith("/Notes/Projects/Home/Kitchen Remodel/20")
    assert "kitchen-remodel-planning.md" in fake_client.moved[0][1]
    assert fake_client.writes
    assert "## Actions" in fake_client.writes[0][1]
    assert "## Raw Note Content" in fake_client.writes[0][1]


def test_process_inbox_unfiles_readable_note_when_file_agent_fails(monkeypatch) -> None:
    fake_client = _ReadableProcessClient()
    queued: list[dict[str, object]] = []

    monkeypatch.setattr(file_inbox, "McpNextcloudClient", lambda url: fake_client)
    monkeypatch.setattr(file_inbox, "_index_document", lambda **kwargs: False)
    monkeypatch.setattr(file_inbox, "_create_file_question", lambda **kwargs: queued.append(kwargs))
    monkeypatch.setattr(
        file_inbox,
        "synthesize_note_with_file_agent",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("gateway unavailable")),
    )

    summary = asyncio.run(
        file_inbox.process_inbox_async(
            mcp_url="http://nextcloud-mcp:8000/mcp",
            ready_tag="ready",
            decision_api_base_url="http://decision-api:8000/v1",
            actor="u@example.com",
            family_id=2,
            nextcloud_base_url="https://nextcloud.example",
        )
    )

    assert summary["processed"] == 1
    assert summary["unfiled"] == 1
    assert summary["results"][0]["folder"] == "Unfiled"
    assert fake_client.moved[0][1].startswith("/Notes/Unfiled/")
    assert fake_client.writes == []
    assert len(queued) == 1


def test_process_inbox_does_not_rewrite_descriptive_markdown(monkeypatch) -> None:
    fake_client = _ReadableProcessClient()
    fake_client.ready[0].path = "/Notes/Inbox/church-notes.md"
    fake_client.ready[0].name = "church-notes.md"
    fake_client.ready[0].source_kind = "ready-tag"
    fake_client.inbox_entries[0]["path"] = "/Notes/Inbox/church-notes.md"
    fake_client.inbox_entries[0]["name"] = "church-notes.md"

    async def _read_file(path: str) -> dict[str, object]:
        assert path == "/Notes/Inbox/church-notes.md"
        return {
            "path": path,
            "content_type": "text/markdown",
            "content": "These are church notes.\nHelping people stay grounded.",
        }

    fake_client.read_file = _read_file  # type: ignore[method-assign]

    monkeypatch.setattr(file_inbox, "McpNextcloudClient", lambda url: fake_client)
    monkeypatch.setattr(file_inbox, "_index_document", lambda **kwargs: True)
    monkeypatch.setattr(
        file_inbox,
        "synthesize_note_with_file_agent",
        lambda **kwargs: file_inbox.FileAgentInboxDecision(
            folder="Areas",
            subfolder_path="Church",
            title="Church Notes",
            filename_slug="church-notes",
            summary="Church notes focused on staying grounded.",
            key_insights=["Encouragement to stay grounded."],
            actions=[],
            open_questions=[],
            rewritten_markdown="# Church Notes\n",
            high_level_category="church",
            sentiment="positive",
            confidence=0.93,
            reason="church-note",
        ),
    )

    summary = asyncio.run(
        file_inbox.process_inbox_async(
            mcp_url="http://nextcloud-mcp:8000/mcp",
            ready_tag="ready",
            decision_api_base_url="http://decision-api:8000/v1",
            actor="u@example.com",
            family_id=2,
            nextcloud_base_url="https://nextcloud.example",
        )
    )

    assert summary["processed"] == 1
    assert summary["results"][0]["folder"] == "Areas"
    assert fake_client.moved[0][1].startswith("/Notes/Areas/Church/")
    assert fake_client.writes == []


def test_process_inbox_closed_mode_processes_unready_files(monkeypatch) -> None:
    fake_client = _ProcessClient()
    fake_client.ready = []

    monkeypatch.setattr(file_inbox, "McpNextcloudClient", lambda url: fake_client)
    monkeypatch.setattr(file_inbox, "_index_document", lambda **kwargs: False)
    monkeypatch.setattr(
        file_inbox,
        "synthesize_note_with_file_agent",
        lambda **kwargs: file_inbox.FileAgentInboxDecision(
            folder="Areas",
            subfolder_path="School/Assignments/Valerie",
            title="School Packet",
            filename_slug="school-packet",
            summary="A school packet.",
            key_insights=[],
            actions=[],
            open_questions=[],
            rewritten_markdown="",
            high_level_category="school",
            sentiment="neutral",
            confidence=0.92,
            reason="school-packet",
        ),
    )

    summary = asyncio.run(
        file_inbox.process_inbox_async(
            mcp_url="http://nextcloud-mcp:8000/mcp",
            ready_tag="ready",
            decision_api_base_url="http://decision-api:8000/v1",
            actor="u@example.com",
            family_id=2,
            nextcloud_base_url="https://nextcloud.example",
            candidate_mode="closed-inbox",
        )
    )

    assert summary["processed"] == 1
    assert summary["unfiled"] == 0
    assert summary["results"][0]["folder"] == "Areas"
    assert fake_client.moved[0][0] == "/Notes/Inbox/scan.pdf"
    assert fake_client.moved[0][1].startswith("/Notes/Areas/School/Assignments/Valerie/")
    assert fake_client.tag_removals == []


def test_replay_unfiled_to_inbox_moves_files_and_skips_attachment_directories(monkeypatch) -> None:
    fake_client = _ProcessClient()
    fake_client.inbox_entries = []
    fake_client.unfiled_entries = [
        {
            "path": "/Notes/Unfiled/.attachments.6242",
            "name": ".attachments.6242",
            "size": 0,
            "content_type": "",
            "last_modified": None,
            "is_directory": True,
            "lock_owner": "",
        },
        {
            "path": "/Notes/Unfiled/2026-03-23_234632_these-are-church-notes.md",
            "name": "2026-03-23_234632_these-are-church-notes.md",
            "size": 1434,
            "content_type": "text/markdown",
            "last_modified": _iso(datetime.now(UTC) - timedelta(minutes=20)),
            "etag": "etag-unfiled",
            "file_id": "file-unfiled",
            "is_directory": False,
            "lock_owner": "",
        },
    ]

    async def _list_directory(path: str) -> list[dict[str, object]]:
        if path == "/Notes/Unfiled":
            return list(fake_client.unfiled_entries)
        return []

    fake_client.list_directory = _list_directory  # type: ignore[method-assign]
    monkeypatch.setattr(file_inbox, "McpNextcloudClient", lambda url: fake_client)

    async def _fake_process_candidates_async(**kwargs):
        return {"status": "completed", "processed": len(kwargs["candidates"])}

    monkeypatch.setattr(file_inbox, "_process_candidates_async", _fake_process_candidates_async)

    summary = asyncio.run(
        file_inbox.replay_unfiled_to_inbox_async(
            mcp_url="http://nextcloud-mcp:8000/mcp",
            ready_tag="ready",
            decision_api_base_url="http://decision-api:8000/v1",
            actor="u@example.com",
            family_id=2,
        )
    )

    assert summary["moved"] == 1
    assert summary["results"] == [
        {
            "source_path": "/Notes/Unfiled/2026-03-23_234632_these-are-church-notes.md",
            "destination_path": "/Notes/Inbox/2026-03-23_234632_these-are-church-notes.md",
        }
    ]
    assert summary["process_summary"]["processed"] == 1
