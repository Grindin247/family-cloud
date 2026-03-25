from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

ARCHIVE_ROOT = "/Notes/Areas/Family Cloud/Overnight Briefings"

REPORT_FRONTMATTER_KEYS = (
    "report_type",
    "agent",
    "family_id",
    "generated_at",
    "time_window",
    "sources",
    "queued_question_ids",
    "safe_updates",
    "confidence",
)

REPORT_SECTION_ORDER = (
    ("Executive Summary", "executive_summary"),
    ("Signals", "signals"),
    ("Anomalies / Gaps", "anomalies_or_gaps"),
    ("Recommendations", "recommendations"),
    ("Queued Questions", "queued_questions"),
    ("Sources", "sources"),
)

MORNING_BRIEF_SECTION_ORDER = (
    ("What Matters Today", "what_matters_today"),
    ("Plan And Life Optimization", "plan_and_life_optimization"),
    ("Upcoming / Travel / Calendar", "upcoming_travel_calendar"),
    ("Relevant News", "relevant_news"),
    ("Open Questions", "open_questions"),
    ("System Gaps", "system_gaps"),
)

REPORT_PATH_SUFFIXES = {
    "amelia_discovery": "amelia-overnight-discovery",
    "caleb_ops": "caleb-overnight-ops",
    "morning_brief": "morning-brief",
}


def archive_path_for_kind(report_date: str, kind: str) -> str:
    if kind not in REPORT_PATH_SUFFIXES:
        raise ValueError(f"unsupported report kind: {kind}")
    return f"{ARCHIVE_ROOT}/{report_date}_{REPORT_PATH_SUFFIXES[kind]}.md"


def _ordered_unique(values: Iterable[Any]) -> list[Any]:
    seen: set[str] = set()
    deduped: list[Any] = []
    for value in values:
        key = json.dumps(value, sort_keys=True, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(value)
    return deduped


def _normalize_source_list(value: Any) -> list[Any]:
    if not isinstance(value, list):
        return []
    normalized: list[Any] = []
    for item in value:
        if isinstance(item, dict):
            normalized.append({str(key): item[key] for key in item})
        elif item not in (None, ""):
            normalized.append(str(item))
    return _ordered_unique(normalized)


def _normalize_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    items = [str(item) for item in value if item not in (None, "")]
    return [str(item) for item in _ordered_unique(items)]


def _normalize_safe_updates(value: Any) -> list[Any]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return _ordered_unique(value)
    return [value]


def _normalize_section_block(value: Any) -> Any:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return list(value)
    return value


def normalize_report_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    normalized.setdefault("report_type", "overnight_report")
    normalized.setdefault("agent", "Unknown")
    normalized.setdefault("family_id", 2)
    normalized.setdefault("generated_at", "")
    normalized.setdefault("time_window", "")
    normalized["sources"] = _normalize_source_list(normalized.get("sources"))
    normalized["queued_question_ids"] = _normalize_string_list(normalized.get("queued_question_ids"))
    normalized["safe_updates"] = _normalize_safe_updates(normalized.get("safe_updates"))
    normalized.setdefault("confidence", "medium")
    for _, key in REPORT_SECTION_ORDER:
        if key == "sources":
            normalized[key] = normalized["sources"]
            continue
        normalized[key] = _normalize_section_block(normalized.get(key))
    return normalized


def normalize_morning_brief_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    normalized.setdefault("report_type", "morning_brief")
    normalized.setdefault("agent", "Caleb")
    normalized.setdefault("family_id", 2)
    normalized.setdefault("generated_at", "")
    normalized.setdefault("time_window", "")
    normalized["sources"] = _normalize_source_list(normalized.get("sources"))
    normalized["queued_question_ids"] = _normalize_string_list(normalized.get("queued_question_ids"))
    normalized["safe_updates"] = _normalize_safe_updates(normalized.get("safe_updates"))
    normalized.setdefault("confidence", "medium")
    for _, key in MORNING_BRIEF_SECTION_ORDER:
        normalized[key] = _normalize_section_block(normalized.get(key))
    return normalized


def _yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def _yaml_lines(value: Any, *, indent: int = 0) -> list[str]:
    prefix = " " * indent
    if isinstance(value, dict):
        if not value:
            return [prefix + "{}"]
        lines: list[str] = []
        for key, item in value.items():
            key_text = str(key)
            if isinstance(item, (dict, list)):
                lines.append(f"{prefix}{key_text}:")
                lines.extend(_yaml_lines(item, indent=indent + 2))
            else:
                lines.append(f"{prefix}{key_text}: {_yaml_scalar(item)}")
        return lines
    if isinstance(value, list):
        if not value:
            return [prefix + "[]"]
        lines = []
        for item in value:
            if isinstance(item, (dict, list)):
                lines.append(f"{prefix}-")
                lines.extend(_yaml_lines(item, indent=indent + 2))
            else:
                lines.append(f"{prefix}- {_yaml_scalar(item)}")
        return lines
    return [prefix + _yaml_scalar(value)]


def _render_frontmatter(payload: dict[str, Any]) -> str:
    lines = ["---"]
    for key in REPORT_FRONTMATTER_KEYS:
        value = payload.get(key)
        if isinstance(value, (dict, list)):
            lines.append(f"{key}:")
            lines.extend(_yaml_lines(value, indent=2))
        else:
            lines.append(f"{key}: {_yaml_scalar(value)}")
    lines.append("---")
    return "\n".join(lines)


def _format_source_item(item: Any) -> str:
    if isinstance(item, str):
        return item
    if not isinstance(item, dict):
        return json.dumps(item, sort_keys=True, ensure_ascii=False)
    label = item.get("label") or item.get("title") or item.get("id") or item.get("source") or item.get("url")
    url = item.get("url")
    note = item.get("note") or item.get("summary")
    text = str(label) if label not in (None, "") else json.dumps(item, sort_keys=True, ensure_ascii=False)
    if url and url != label:
        text = f"{text} - {url}"
    if note not in (None, ""):
        text = f"{text} ({note})"
    return text


def _render_markdown_block(value: Any, *, sources_mode: bool = False) -> str:
    if value in (None, "", [], {}):
        return "None noted."
    if isinstance(value, str):
        return value.strip() or "None noted."
    if isinstance(value, list):
        if not value:
            return "None noted."
        lines: list[str] = []
        for item in value:
            if sources_mode:
                lines.append(f"- {_format_source_item(item)}")
            elif isinstance(item, str):
                lines.append(f"- {item}")
            else:
                lines.append(f"- {json.dumps(item, sort_keys=True, ensure_ascii=False)}")
        return "\n".join(lines)
    return "```json\n" + json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n```"


def _render_sections(payload: dict[str, Any], section_order: tuple[tuple[str, str], ...]) -> str:
    blocks: list[str] = []
    for title, key in section_order:
        value = payload.get(key)
        blocks.append(f"## {title}\n{_render_markdown_block(value, sources_mode=(key == 'sources'))}")
    return "\n\n".join(blocks)


def render_report(payload: dict[str, Any]) -> str:
    normalized = normalize_report_payload(payload)
    return _render_frontmatter(normalized) + "\n\n" + _render_sections(normalized, REPORT_SECTION_ORDER) + "\n"


def render_morning_brief(payload: dict[str, Any]) -> str:
    normalized = normalize_morning_brief_payload(payload)
    return _render_frontmatter(normalized) + "\n\n" + _render_sections(normalized, MORNING_BRIEF_SECTION_ORDER) + "\n"


def _load_payload(path_value: str) -> dict[str, Any]:
    if path_value == "-":
        raw = sys.stdin.read()
    else:
        raw = Path(path_value).read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("expected top-level JSON object payload")
    return data


def _write_output(text: str, output_path: str | None) -> None:
    if output_path:
        Path(output_path).write_text(text, encoding="utf-8")
        return
    sys.stdout.write(text)


def main() -> int:
    parser = argparse.ArgumentParser(description="Render standardized overnight reports and morning briefs.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    path_parser = subparsers.add_parser("path", help="Print the deterministic archive path for a report kind.")
    path_parser.add_argument("--date", required=True, help="Report date in YYYY-MM-DD format.")
    path_parser.add_argument("--kind", required=True, choices=sorted(REPORT_PATH_SUFFIXES), help="Archive kind.")

    report_parser = subparsers.add_parser("render-report", help="Render an overnight report markdown note from JSON.")
    report_parser.add_argument("--input", default="-", help="JSON payload path, or '-' for stdin.")
    report_parser.add_argument("--output", help="Optional markdown output path.")

    brief_parser = subparsers.add_parser("render-brief", help="Render a morning brief markdown note from JSON.")
    brief_parser.add_argument("--input", default="-", help="JSON payload path, or '-' for stdin.")
    brief_parser.add_argument("--output", help="Optional markdown output path.")

    args = parser.parse_args()

    if args.command == "path":
        sys.stdout.write(archive_path_for_kind(args.date, args.kind) + "\n")
        return 0
    if args.command == "render-report":
        _write_output(render_report(_load_payload(args.input)), args.output)
        return 0
    if args.command == "render-brief":
        _write_output(render_morning_brief(_load_payload(args.input)), args.output)
        return 0
    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
