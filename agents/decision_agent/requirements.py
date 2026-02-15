from __future__ import annotations

from .schemas import DecisionDraft


_MIN_FIELDS_BY_TYPE: dict[str, list[str]] = {
    "travel": ["target_date", "participants", "options"],
    "purchase": ["budget", "options"],
    "life_change": ["options"],
    "other": ["options"],
}


def missing_fields(draft: DecisionDraft) -> list[str]:
    missing: list[str] = []
    if not draft.title.strip():
        missing.append("title")
    if not draft.description.strip():
        missing.append("description")

    required = _MIN_FIELDS_BY_TYPE.get(draft.decision_type, _MIN_FIELDS_BY_TYPE["other"])
    for field in required:
        if field == "target_date" and draft.target_date is None:
            missing.append("target_date (date window)")
        elif field == "participants" and not draft.participants:
            missing.append("participants")
        elif field == "budget" and draft.budget is None:
            missing.append("budget")
        elif field == "options" and len(draft.options) < 2:
            missing.append("options (at least 2)")
    return missing

