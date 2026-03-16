from __future__ import annotations

from typing import Any

from agents.common.events.publisher import EventPublisher


_publisher: EventPublisher | None = None


def publisher() -> EventPublisher:
    global _publisher
    if _publisher is None:
        _publisher = EventPublisher()
    return _publisher


def publish_event(
    subject: str,
    payload: dict[str, Any],
    *,
    actor: str,
    family_id: int,
    source: str,
    correlation_id: str | None = None,
    headers: dict[str, str] | None = None,
) -> str:
    # Sync publishing is fine at this stage; replace with async/background task later.
    return publisher().publish_sync(
        subject,
        payload,
        actor=actor,
        family_id=family_id,
        source=source,
        correlation_id=correlation_id,
        headers=headers,
    )

