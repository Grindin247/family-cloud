from __future__ import annotations

import importlib.util
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MODULE_PATH = ROOT / "scripts" / "nextcloud_para_agent.py"
SPEC = importlib.util.spec_from_file_location("nextcloud_para_agent", MODULE_PATH)
assert SPEC is not None
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_script_standalone_help_bootstraps_repo_root() -> None:
    result = subprocess.run(
        [sys.executable, str(MODULE_PATH), "--help"],
        cwd=str(ROOT / "scripts"),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "process-ready" in result.stdout
    assert "replay-unfiled" in result.stdout


def test_readable_markdown_with_project_context_goes_to_projects() -> None:
    decision = MODULE.derive_filing_decision(
        path="/Notes/Inbox/Untitled.md",
        content_type="text/markdown",
        readable_text="# Kitchen remodel project plan\nBudget and contractor notes",
        timestamp=datetime(2026, 3, 17, 9, 30, tzinfo=UTC),
    )
    assert decision["folder"] == "Projects"
    assert decision["filename"].startswith("2026-03-17_093000_")
    assert decision["filename"].endswith(".md")


def test_readable_area_document_goes_to_areas() -> None:
    decision = MODULE.derive_filing_decision(
        path="/Notes/Inbox/scan.txt",
        content_type="text/plain",
        readable_text="School calendar and kids routine updates for April",
        timestamp=datetime(2026, 3, 17, 9, 30, tzinfo=UTC),
    )
    assert decision["folder"] == "Areas"


def test_unreadable_descriptive_file_can_still_be_filed() -> None:
    decision = MODULE.derive_filing_decision(
        path="/Notes/Inbox/2026-home-insurance-policy.pdf",
        content_type="application/pdf",
        readable_text=None,
        timestamp=datetime(2026, 3, 17, 9, 30, tzinfo=UTC),
    )
    assert decision["folder"] in {"Areas", "Archive", "Resources"}
    assert decision["folder"] != "Unfiled"
    assert decision["filename"].endswith(".pdf")


def test_unreadable_generic_file_goes_to_unfiled() -> None:
    decision = MODULE.derive_filing_decision(
        path="/Notes/Inbox/scan.pdf",
        content_type="application/pdf",
        readable_text=None,
        timestamp=datetime(2026, 3, 17, 9, 30, tzinfo=UTC),
    )
    assert decision["folder"] == "Unfiled"


def test_file_item_type_prefers_note_for_readable_markdown() -> None:
    item_type = MODULE.infer_file_item_type("text/markdown", ".md", "hello")
    assert item_type == "note"


def test_migration_collects_moves_and_skips_conflicts() -> None:
    class FakeClient:
        def list_directory(self, path: str):
            mapping = {
                "/Notes/FamilyCloud": [
                    {"path": "/Notes/FamilyCloud/Projects", "is_directory": True},
                    {"path": "/Notes/FamilyCloud/Areas", "is_directory": True},
                ],
                "/Notes/FamilyCloud/Projects": [
                    {"path": "/Notes/FamilyCloud/Projects/kitchen.md", "is_directory": False},
                ],
                "/Notes/FamilyCloud/Areas": [
                    {"path": "/Notes/FamilyCloud/Areas/school.md", "is_directory": False},
                ],
            }
            return mapping.get(path, [])

        def path_exists(self, path: str) -> bool:
            return path == "/Notes/Areas/school.md"

    moves, conflicts, directories = MODULE._collect_migration_moves(FakeClient(), "/Notes/FamilyCloud")
    assert moves == [("/Notes/FamilyCloud/Projects/kitchen.md", "/Notes/Projects/kitchen.md")]
    assert conflicts == ["/Notes/Areas/school.md"]
    assert directories == ["/Notes/FamilyCloud", "/Notes/FamilyCloud/Areas", "/Notes/FamilyCloud/Projects"]


def test_default_base_url_reads_repo_env_when_process_env_is_empty(monkeypatch) -> None:
    monkeypatch.delenv("NEXTCLOUD_BASE_URL", raising=False)
    monkeypatch.delenv("NEXT_PUBLIC_FAMILY_DOMAIN", raising=False)
    monkeypatch.delenv("FAMILY_DOMAIN", raising=False)
    MODULE._load_repo_env.cache_clear()
    assert MODULE._default_base_url() == "https://nextcloud.family.callender"
    MODULE._load_repo_env.cache_clear()


def test_default_file_api_base_url_prefers_localhost_port(monkeypatch) -> None:
    monkeypatch.delenv("FILE_API_BASE_URL", raising=False)
    monkeypatch.delenv("FILE_API_PORT", raising=False)
    monkeypatch.delenv("DECISION_API_BASE_URL", raising=False)
    monkeypatch.delenv("DECISION_API_PORT", raising=False)
    MODULE._load_repo_env.cache_clear()
    assert MODULE._default_file_api_base_url() == "http://127.0.0.1:8070/v1"
    MODULE._load_repo_env.cache_clear()


def test_default_actor_reads_nextcloud_username_file(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("FILE_AGENT_ACTOR", raising=False)
    monkeypatch.delenv("HOME_PORTAL_FILE_AGENT_ACTOR", raising=False)
    monkeypatch.delenv("NEXTCLOUD_AUTOMATION_USERNAME", raising=False)
    monkeypatch.delenv("NEXTCLOUD_USERNAME", raising=False)
    monkeypatch.setattr(MODULE, "_load_repo_env", lambda: {})
    monkeypatch.setattr(MODULE, "_load_identity_registry", lambda: {})
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    (secrets_dir / "nextcloud_mcp_username").write_text("agent@example.com\n", encoding="utf-8")
    monkeypatch.setattr(MODULE.Path, "resolve", lambda self: tmp_path / "scripts" / "nextcloud_para_agent.py")

    assert MODULE._default_actor() == "agent@example.com"


def test_default_actor_prefers_repo_file_agent_actor_over_non_email_username(monkeypatch) -> None:
    monkeypatch.delenv("FILE_AGENT_ACTOR", raising=False)
    monkeypatch.delenv("HOME_PORTAL_FILE_AGENT_ACTOR", raising=False)
    monkeypatch.delenv("NEXTCLOUD_AUTOMATION_USERNAME", raising=False)
    monkeypatch.delenv("NEXTCLOUD_USERNAME", raising=False)
    monkeypatch.setattr(MODULE, "_load_repo_env", lambda: {"FILE_AGENT_ACTOR": "mrjamescallender@gmail.com"})
    monkeypatch.setattr(MODULE, "_load_identity_registry", lambda: {})

    assert MODULE._default_actor() == "mrjamescallender@gmail.com"


def test_replay_unfiled_async_moves_then_processes(monkeypatch) -> None:
    captured: list[str] = []

    async def _fake_replay(**kwargs):
        captured.append("replay")
        assert kwargs["source_path"] == "/Notes/Unfiled"
        assert kwargs["target_path"] == "/Notes/Inbox"
        assert kwargs["actor"] == "u@example.com"
        return {
            "moved": 2,
            "results": [{"source_path": "/Notes/Unfiled/a.pdf", "destination_path": "/Notes/Inbox/a.pdf"}],
            "process_summary": {"status": "completed", "processed": 2},
        }

    monkeypatch.setattr(MODULE, "shared_replay_unfiled_to_inbox_async", _fake_replay)

    args = MODULE.build_parser().parse_args(
        [
            "--mcp-url",
            "http://nextcloud-mcp:8000/mcp",
            "replay-unfiled",
            "--actor",
            "u@example.com",
        ]
    )
    summary = MODULE.asyncio.run(MODULE.replay_unfiled_async(args))

    assert captured == ["replay"]
    assert summary["replayed"] == 2
    assert summary["process_summary"]["processed"] == 2


def test_process_ready_async_passes_max_files_to_shared_processor(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def _fake_process(**kwargs):
        captured.update(kwargs)
        return {"status": "completed", "processed": 0}

    monkeypatch.setattr(MODULE, "shared_process_inbox_async", _fake_process)

    args = MODULE.build_parser().parse_args(
        [
            "process-ready",
            "--actor",
            "u@example.com",
            "--max-files",
            "8",
        ]
    )
    summary = MODULE.asyncio.run(MODULE.process_ready_files_async(args))

    assert summary["status"] == "completed"
    assert captured["max_candidates"] == 8
