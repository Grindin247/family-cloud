from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from agents.common.observability.tracing import new_correlation_id as _new_correlation_id

from .models import EventCorrelation, EventIntegrity, EventPrivacy, FamilyEvent


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime | None) -> datetime:
    if value is None:
        return _utcnow()
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def new_event_id() -> str:
    return str(uuid.uuid4())


def new_correlation_id() -> str:
    return _new_correlation_id()


def make_privacy(
    *,
    classification: str = "family",
    contains_pii: bool = False,
    contains_health_data: bool = False,
    contains_financial_data: bool = False,
    contains_child_data: bool = False,
    contains_free_text: bool = False,
    export_policy: str = "restricted",
) -> dict[str, Any]:
    return EventPrivacy(
        classification=classification,
        contains_pii=contains_pii,
        contains_health_data=contains_health_data,
        contains_financial_data=contains_financial_data,
        contains_child_data=contains_child_data,
        contains_free_text=contains_free_text,
        export_policy=export_policy,
    ).model_dump(mode="json")


def validate_event_envelope(event: dict[str, Any]) -> None:
    FamilyEvent.model_validate(event)


def build_event(
    *,
    family_id: int,
    domain: str,
    event_type: str,
    actor: dict[str, Any],
    subject: dict[str, Any],
    payload: dict[str, Any],
    source: dict[str, Any],
    privacy: dict[str, Any],
    tags: list[str] | None = None,
    correlation_id: str | None = None,
    causation_id: str | None = None,
    parent_event_id: str | None = None,
    occurred_at: datetime | None = None,
    recorded_at: datetime | None = None,
    event_version: int = 1,
    integrity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event = FamilyEvent(
        event_id=new_event_id(),
        schema_version=1,
        occurred_at=_as_utc(occurred_at),
        recorded_at=_as_utc(recorded_at),
        family_id=family_id,
        domain=domain,
        event_type=event_type,
        event_version=event_version,
        actor=actor,
        subject=subject,
        source=source,
        correlation=EventCorrelation(
            correlation_id=correlation_id,
            causation_id=causation_id,
            parent_event_id=parent_event_id,
        ),
        privacy=privacy,
        payload=payload,
        tags=tags or [],
        integrity=EventIntegrity.model_validate(integrity) if integrity else None,
    )
    return event.model_dump(mode="json")
