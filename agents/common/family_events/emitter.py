from __future__ import annotations

from typing import Any

from .builder import build_event, make_privacy


def emit_canonical_event(
    *,
    family_id: int,
    domain: str,
    event_type: str,
    actor_id: str,
    actor_type: str,
    subject_type: str,
    subject_id: str,
    source_agent_id: str,
    source_runtime: str,
    payload: dict[str, Any],
    tags: list[str] | None = None,
    correlation_id: str | None = None,
    source_request_id: str | None = None,
    source_session_id: str | None = None,
    privacy: dict[str, Any] | None = None,
) -> str:
    event = build_event(
        family_id=family_id,
        domain=domain,
        event_type=event_type,
        actor={"actor_type": actor_type, "actor_id": actor_id},
        subject={"subject_type": subject_type, "subject_id": subject_id},
        payload=payload,
        source={
            "agent_id": source_agent_id,
            "runtime": source_runtime,
            "request_id": source_request_id,
            "session_id": source_session_id,
        },
        privacy=privacy or make_privacy(),
        tags=tags,
        correlation_id=correlation_id,
        integrity={"producer": source_agent_id},
    )
    from .publisher import publish_event

    return publish_event(event)
