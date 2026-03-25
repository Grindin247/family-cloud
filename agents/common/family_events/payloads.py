from __future__ import annotations

from typing import Any


def collapse_whitespace(value: str) -> str:
    return " ".join(value.split())


def text_snippet(value: Any, *, max_chars: int = 240) -> str | None:
    if value is None:
        return None
    text = collapse_whitespace(str(value).strip())
    if not text:
        return None
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def snippet_fields(field_name: str, value: Any, *, max_chars: int = 240) -> dict[str, Any]:
    if value is None:
        return {}
    text = collapse_whitespace(str(value).strip())
    if not text:
        return {}
    return {
        f"{field_name}_snippet": text_snippet(text, max_chars=max_chars),
        f"{field_name}_char_count": len(text),
    }


def diff_field_paths(before: Any, after: Any, *, prefix: str = "") -> list[str]:
    if before == after:
        return []
    if isinstance(before, dict) and isinstance(after, dict):
        keys = sorted(set(before) | set(after))
        changed: list[str] = []
        for key in keys:
            next_prefix = f"{prefix}.{key}" if prefix else str(key)
            changed.extend(diff_field_paths(before.get(key), after.get(key), prefix=next_prefix))
        return changed
    if isinstance(before, list) and isinstance(after, list):
        return [prefix] if prefix else ["value"]
    return [prefix] if prefix else ["value"]

