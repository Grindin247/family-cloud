from datetime import UTC, datetime

import pytest

from agents.common.family_events import build_event, make_privacy, subject_for_domain, validate_event_envelope


def test_build_event_normalizes_and_validates():
    event = build_event(
        family_id=2,
        domain="task",
        event_type="task.completed",
        actor={"actor_type": "user", "actor_id": "mrjamescallender@gmail.com"},
        subject={"subject_type": "task", "subject_id": "123"},
        payload={"task_id": 123, "completed_by": "mrjamescallender@gmail.com"},
        source={"agent_id": "TaskAgent", "runtime": "openclaw-subagent"},
        privacy=make_privacy(),
        tags=[" Church ", "church"],
        occurred_at=datetime(2026, 3, 16, 12, 0, tzinfo=UTC),
        recorded_at=datetime(2026, 3, 16, 12, 1, tzinfo=UTC),
    )
    validate_event_envelope(event)
    assert event["tags"] == ["church", "church"]


def test_subject_for_domain():
    assert subject_for_domain("decision") == "family.events.decision"
    assert subject_for_domain("note") == "family.events.file"


def test_invalid_agent_id_rejected():
    with pytest.raises(Exception):
        validate_event_envelope(
            build_event(
                family_id=2,
                domain="decision",
                event_type="decision.created",
                actor={"actor_type": "user", "actor_id": "u@example.com"},
                subject={"subject_type": "decision", "subject_id": "12"},
                payload={"decision_id": 12},
                source={"agent_id": "BadAgent", "runtime": "backend"},
                privacy=make_privacy(),
            )
        )
