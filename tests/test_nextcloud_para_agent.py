from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "nextcloud_para_agent.py"
SPEC = importlib.util.spec_from_file_location("nextcloud_para_agent", MODULE_PATH)
assert SPEC is not None
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


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
