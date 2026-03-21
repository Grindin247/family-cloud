from __future__ import annotations

import asyncio
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
            "title": "Kitchen Remodel Planning Notes",
            "filename_slug": "kitchen-remodel-plan",
            "summary": "This note captures the remodel planning conversation and the next coordination steps.",
            "key_insights": ["Cabinet samples still need to be finalized."],
            "actions": ["Call the contractor by Friday."],
            "open_questions": ["Do we need a permit for moving the sink?"],
            "confidence": 0.88,
            "reason": "project-planning-note",
        },
        "Raw kitchen remodel text",
    )

    assert decision.folder == "Projects"
    assert decision.filename_slug == "kitchen-remodel-plan"
    assert "## Actions" in decision.rewritten_markdown
    assert "## Raw Note Content" in decision.rewritten_markdown
    assert decision.summary.startswith("This note captures")
    assert decision.actions == ["Call the contractor by Friday."]


def test_infer_file_item_type_keeps_ocr_images_as_images() -> None:
    assert file_inbox.infer_file_item_type("image/png", ".png", "Receipt total 18.42") == "image"


def test_process_inbox_falls_back_to_unfiled_for_low_confidence_files(monkeypatch) -> None:
    fake_client = _ProcessClient()
    queued: list[dict[str, object]] = []

    monkeypatch.setattr(file_inbox, "McpNextcloudClient", lambda url: fake_client)
    monkeypatch.setattr(file_inbox, "_index_document", lambda **kwargs: False)
    monkeypatch.setattr(file_inbox, "_create_file_question", lambda **kwargs: queued.append(kwargs))

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
    assert summary["results"][0]["confidence"] < 0.7
    assert fake_client.moved[0][0] == "/Notes/Inbox/scan.pdf"
    assert fake_client.moved[0][1].startswith("/Notes/Unfiled/")
    assert fake_client.tag_removals == [("file-1", "ready")]
    assert len(queued) == 1


def test_process_inbox_uses_file_agent_for_readable_notes(monkeypatch) -> None:
    fake_client = _ReadableProcessClient()

    monkeypatch.setattr(file_inbox, "McpNextcloudClient", lambda url: fake_client)
    monkeypatch.setattr(file_inbox, "_index_document", lambda **kwargs: True)
    monkeypatch.setattr(
        file_inbox,
        "synthesize_note_with_file_agent",
        lambda **kwargs: file_inbox.FileAgentInboxDecision(
            folder="Projects",
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
    assert fake_client.moved[0][1].startswith("/Notes/Projects/20")
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
