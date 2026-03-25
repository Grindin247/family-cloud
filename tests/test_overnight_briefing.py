from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "overnight_briefing.py"
SPEC = importlib.util.spec_from_file_location("overnight_briefing", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_archive_paths_are_deterministic_for_same_day_reruns() -> None:
    assert MODULE.archive_path_for_kind("2026-03-24", "amelia_discovery") == (
        "/Notes/Areas/Family Cloud/Overnight Briefings/2026-03-24_amelia-overnight-discovery.md"
    )
    assert MODULE.archive_path_for_kind("2026-03-24", "caleb_ops") == (
        "/Notes/Areas/Family Cloud/Overnight Briefings/2026-03-24_caleb-overnight-ops.md"
    )
    assert MODULE.archive_path_for_kind("2026-03-24", "morning_brief") == (
        "/Notes/Areas/Family Cloud/Overnight Briefings/2026-03-24_morning-brief.md"
    )


def test_normalize_report_payload_dedupes_question_ids_and_sources() -> None:
    payload = {
        "report_type": "overnight_discovery",
        "agent": "Amelia",
        "family_id": 2,
        "generated_at": "2026-03-24T22:30:00-04:00",
        "time_window": "2026-03-24",
        "sources": [
            {"label": "Travel article", "url": "https://example.com/travel", "note": "Spring trip ideas"},
            {"label": "Travel article", "url": "https://example.com/travel", "note": "Spring trip ideas"},
            "calendar:next-30-days",
            "calendar:next-30-days",
        ],
        "queued_question_ids": ["q-1", "q-1", "q-2"],
        "safe_updates": [{"kind": "question", "id": "q-1"}, {"kind": "question", "id": "q-1"}],
        "executive_summary": ["Trip planning signal detected."],
    }

    normalized = MODULE.normalize_report_payload(payload)

    assert normalized["queued_question_ids"] == ["q-1", "q-2"]
    assert normalized["sources"] == [
        {"label": "Travel article", "url": "https://example.com/travel", "note": "Spring trip ideas"},
        "calendar:next-30-days",
    ]
    assert normalized["safe_updates"] == [{"kind": "question", "id": "q-1"}]


def test_render_report_preserves_contract_sections_and_citations() -> None:
    text = MODULE.render_report(
        {
            "report_type": "overnight_ops",
            "agent": "Caleb",
            "family_id": 2,
            "generated_at": "2026-03-25T01:30:00-04:00",
            "time_window": {"start": "2026-03-24T22:00:00-04:00", "end": "2026-03-25T01:30:00-04:00"},
            "sources": [{"label": "Event summary", "url": "https://example.com/events"}],
            "queued_question_ids": ["q-7"],
            "safe_updates": [{"kind": "question", "id": "q-7"}],
            "executive_summary": ["Task backlog is stable."],
            "signals": ["Bench press goal is active."],
            "anomalies_or_gaps": ["No household location on profile; local-news curation skipped."],
            "recommendations": ["Suggest a higher-protein breakfast option."],
            "queued_questions": ["q-7: confirm ideal training days"],
        }
    )

    assert text.startswith("---\nreport_type:")
    assert "## Executive Summary" in text
    assert "## Signals" in text
    assert "## Anomalies / Gaps" in text
    assert "## Recommendations" in text
    assert "## Queued Questions" in text
    assert "## Sources" in text
    assert "https://example.com/events" in text


def test_render_morning_brief_uses_required_section_order() -> None:
    text = MODULE.render_morning_brief(
        {
            "generated_at": "2026-03-25T08:05:00-04:00",
            "sources": [{"label": "News", "url": "https://example.com/news"}],
            "queued_question_ids": ["q-1", "q-1"],
            "what_matters_today": ["School pickup time moved earlier."],
            "plan_and_life_optimization": ["Protein-heavy breakfast supports the current strength plan."],
            "upcoming_travel_calendar": ["Summer vacation research is active."],
            "relevant_news": ["One national travel advisory is worth reviewing."],
            "open_questions": ["q-1: do you want beach or mountains this summer?"],
            "system_gaps": ["Household location missing, so no speculative local news was included."],
        }
    )

    expected_headers = [
        "## What Matters Today",
        "## Plan And Life Optimization",
        "## Upcoming / Travel / Calendar",
        "## Relevant News",
        "## Open Questions",
        "## System Gaps",
    ]
    positions = [text.index(header) for header in expected_headers]
    assert positions == sorted(positions)
    assert "https://example.com/news" in text
