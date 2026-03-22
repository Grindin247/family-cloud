from __future__ import annotations

from .models import AllowedDomain


SUBJECT_BY_DOMAIN: dict[AllowedDomain, str] = {
    "decision": "family.events.decision",
    "task": "family.events.task",
    "file": "family.events.file",
    "note": "family.events.file",
    "education": "family.events.education",
    "profile": "family.events.profile",
    "planning": "family.events.planning",
}


def subject_for_domain(domain: AllowedDomain) -> str:
    return SUBJECT_BY_DOMAIN[domain]
