from __future__ import annotations

import re
from typing import Any


_DENY_PATTERNS = [
    re.compile(r"-----BEGIN (RSA|EC|OPENSSH|PGP) PRIVATE KEY-----", re.IGNORECASE),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),  # AWS access key id (classic)
    re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,}\b"),  # Slack tokens
    re.compile(r"\bghp_[0-9A-Za-z]{20,}\b"),  # GitHub PAT (classic)
]

_DENY_KEYWORDS = {"password", "passwd", "secret", "api_key", "apikey", "token", "private_key"}


def scan_no_secrets(value: Any) -> list[str]:
    """
    Returns a list of findings. Empty list means OK.
    """
    findings: list[str] = []

    def _walk(v: Any, path: str) -> None:
        if v is None:
            return
        if isinstance(v, dict):
            for k, child in v.items():
                key = str(k)
                if key.lower() in _DENY_KEYWORDS:
                    findings.append(f"deny_key:{path}/{key}")
                _walk(child, f"{path}/{key}")
            return
        if isinstance(v, list):
            for i, child in enumerate(v):
                _walk(child, f"{path}[{i}]")
            return
        if isinstance(v, (str, bytes)):
            s = v.decode("utf-8", errors="ignore") if isinstance(v, bytes) else v
            low = s.lower()
            for kw in _DENY_KEYWORDS:
                if kw in low:
                    findings.append(f"deny_keyword:{path}")
                    break
            for pat in _DENY_PATTERNS:
                if pat.search(s):
                    findings.append(f"deny_pattern:{path}")
                    break
            return

    _walk(value, "")
    # De-dupe for stable errors.
    return sorted(set(findings))

