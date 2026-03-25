from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.common import retrieval


def _registry(tmp_path: Path) -> Path:
    path = tmp_path / "family-identity.json"
    path.write_text(
        json.dumps(
            {
                "families": [
                    {
                        "family_id": 2,
                        "family_slug": "callender-family",
                        "name": "callender_family",
                        "persons": [
                            {
                                "person_id": "person-1",
                                "display_name": "Dadda Callender",
                                "canonical_name": "Dadda Callender",
                                "aliases": ["dadda", "dad"],
                                "accounts": {"email": ["mrjamescallender@gmail.com"]},
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return path


def test_resolve_actor_context_uses_alias_and_registry_email(tmp_path: Path) -> None:
    context = retrieval.resolve_actor_context(speaker="dad", registry_path=_registry(tmp_path))

    assert context.family_id == 2
    assert context.actor_id == "mrjamescallender@gmail.com"
    assert context.person_id == "person-1"
    assert context.display_name == "Dadda Callender"


def test_search_index_calls_file_service_with_family_wide_defaults(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    class _FakeClient:
        def __init__(self, base_url: str | None = None) -> None:
            captured["base_url"] = base_url

        def request(self, method: str, path: str, *, params=None, json_body=None, headers=None):
            captured["method"] = method
            captured["path"] = path
            captured["json_body"] = json_body
            captured["headers"] = headers
            return type("Result", (), {"result": {"items": [{"path": "/Notes/Resources/Insurance/van.pdf"}]}})()

    monkeypatch.setattr(retrieval, "HttpToolClient", _FakeClient)

    result = retrieval.search_index(
        "documents",
        query_text="van breakdown coverage",
        speaker="Dadda Callender",
        registry_path=_registry(tmp_path),
        base_url="http://127.0.0.1:8070/v1",
    )

    assert captured["method"] == "POST"
    assert captured["path"] == "/search"
    assert captured["headers"] == {"X-Dev-User": "mrjamescallender@gmail.com"}
    assert captured["json_body"] == {
        "family_id": 2,
        "actor": "mrjamescallender@gmail.com",
        "query": "van breakdown coverage",
        "top_k": 5,
        "include_content": True,
        "date_from": None,
        "date_to": None,
        "document_kinds": [],
        "preferred_item_types": [],
        "content_types": [],
        "query_tags": [],
    }
    assert result["response"]["items"][0]["path"] == "/Notes/Resources/Insurance/van.pdf"


def test_resolve_actor_context_can_fall_back_from_family_label(tmp_path: Path) -> None:
    context = retrieval.resolve_actor_context(speaker="Callender Family", registry_path=_registry(tmp_path))

    assert context.family_id == 2
    assert context.actor_id == "mrjamescallender@gmail.com"
    assert context.display_name == "Dadda Callender"


def test_summarize_search_result_keeps_high_signal_fields() -> None:
    summarized = retrieval.summarize_search_result(
        {
            "kind": "documents",
            "query": "van breakdown coverage",
            "resolved_context": {"family_id": 2, "actor_id": "mrjamescallender@gmail.com"},
            "response": {
                "items": [
                    {
                        "document_id": "doc-1",
                        "document_kind": "file",
                        "path": "/Notes/Resources/Insurance/van.pdf",
                        "title": "Vehicle Policy Summary",
                        "summary": "Roadside assistance and breakdown coverage.",
                        "match_reasons": ["Semantic similarity matched the request"],
                        "source_refs": [{"path": "/Notes/Resources/Insurance/van.pdf"}],
                        "unused": "ignore-me",
                    }
                ]
            },
        }
    )

    assert summarized == {
        "ok": True,
        "kind": "documents",
        "query": "van breakdown coverage",
        "resolved_context": {"family_id": 2, "actor_id": "mrjamescallender@gmail.com"},
        "total": 1,
        "items": [
            {
                "rank": 1,
                "document_id": "doc-1",
                "document_kind": "file",
                "path": "/Notes/Resources/Insurance/van.pdf",
                "title": "Vehicle Policy Summary",
                "summary": "Roadside assistance and breakdown coverage.",
                "match_reasons": ["Semantic similarity matched the request"],
                "source_refs": [{"path": "/Notes/Resources/Insurance/van.pdf"}],
            }
        ],
    }
