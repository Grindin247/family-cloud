from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from pydantic import ValidationError

from .schemas import OpsEnvelope


_FENCED_OPS_RE = re.compile(r"---BEGIN_OPS---\s*(\{.*?\})\s*---END_OPS---", flags=re.DOTALL)
_CONTROL_PREFIXES = (
    "note:",
    "notes:",
    "instruction:",
    "instructions:",
    "do not",
    "don't",
    "then",
    "return",
    "action",
    "ops",
    "parameters",
    "move_task",
    "rename",
    "project id",
    "task id",
)


@dataclass
class OpsParseResult:
    triggered: bool
    envelope: OpsEnvelope | None = None
    error: str | None = None
    notes: list[str] = field(default_factory=list)


def parse_ops_message(message: str) -> OpsParseResult:
    payload = _extract_ops_payload(message)
    if payload is None:
        return OpsParseResult(triggered=False)
    try:
        raw = json.loads(payload)
    except json.JSONDecodeError as exc:
        return OpsParseResult(triggered=True, error=f"invalid_ops_json:{exc.msg}")
    try:
        return OpsParseResult(triggered=True, envelope=OpsEnvelope.model_validate(raw))
    except ValidationError as exc:
        return OpsParseResult(triggered=True, error=f"invalid_ops_schema:{exc.errors()}")


def _extract_ops_payload(message: str) -> str | None:
    text = (message or "").strip()
    if not text:
        return None
    if text.startswith("{") and text.endswith("}"):
        try:
            raw = json.loads(text)
        except json.JSONDecodeError:
            raw = None
        if isinstance(raw, dict) and str(raw.get("mode") or "").lower() == "ops":
            return text
    match = _FENCED_OPS_RE.search(text)
    if match:
        return match.group(1).strip()
    if "---BEGIN_OPS---" in text or "---END_OPS---" in text:
        return "{}"
    return None


def is_management_command_without_ops(message: str) -> bool:
    text = (message or "").strip().lower()
    if not text:
        return False
    patterns = (
        r"\bdelete\b.*\b(project|projects|list|lists)\b",
        r"\barchive\b.*\b(project|projects|list|lists)\b",
        r"\bdelete\s+all\s+tasks\b",
        r"\bremove\s+all\s+tasks\b",
        r"\bclear\b.*\b(list|tasks?)\b",
        r"\brename\b.*\b(project|list)\b",
        r"\bmove\b.*\b(project|list)\b",
        r"\bmove\s+\"[^\"]+\"\s+to\b",
        r"\bmove\s+'[^']+'\s+to\b",
        r"\bmove\s+.+\s+to\s+.+",
        r"\bset\s+parent\s+project\b",
        r"\b(move|put)\b.+\bunder\b.+",
        r"\bmove\s+task\b.*\bid\b",
        r"\bmark\s+task\b.*\bcomplete(d)?\b",
        r"\bcomplete\s+task\b",
        r"\bmark\s+\"[^\"]+\"\s+complete(d)?\b",
        r"\bmark\s+'[^']+'\s+complete(d)?\b",
        r"\bcomplete\s+\"[^\"]+\"",
        r"\bcomplete\s+'[^']+'",
        r"\bupdate\s+task\b",
        r"\brename\s+project/list\s+id\b",
        r"\bproject\s+id\s+\d+",
        r"\btask\s+id\s+\d+",
    )
    return any(re.search(pattern, text) for pattern in patterns)


def strip_control_lines(message: str) -> str:
    kept: list[str] = []
    for line in (message or "").splitlines():
        trimmed = line.strip()
        lowered = trimmed.lower()
        if any(lowered.startswith(prefix) for prefix in _CONTROL_PREFIXES):
            continue
        kept.append(line)
    return "\n".join(kept).strip()
