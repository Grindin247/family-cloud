from datetime import UTC, datetime

import pytest

from agents.common.family_events import (
    build_event,
    canonical_subjects,
    diff_field_paths,
    make_privacy,
    snippet_fields,
    subject_for_domain,
    validate_event_envelope,
)


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
    assert subject_for_domain("education") == "family.events.education"
    assert subject_for_domain("planning") == "family.events.planning"
    assert subject_for_domain("question") == "family.events.question"
    assert subject_for_domain("family") == "family.events.family"
    assert canonical_subjects() == [
        "family.events.decision",
        "family.events.education",
        "family.events.family",
        "family.events.file",
        "family.events.planning",
        "family.events.profile",
        "family.events.question",
        "family.events.task",
    ]


def test_education_service_agent_id_allowed():
    event = build_event(
        family_id=2,
        domain="education",
        event_type="education.goal.created",
        actor={"actor_type": "user", "actor_id": "admin@example.com"},
        subject={"subject_type": "education", "subject_id": "goal-1"},
        payload={"goal_id": "goal-1", "entity_type": "goal"},
        source={"agent_id": "EducationService", "runtime": "backend"},
        privacy=make_privacy(contains_child_data=True),
        occurred_at=datetime(2026, 3, 18, 12, 0, tzinfo=UTC),
        recorded_at=datetime(2026, 3, 18, 12, 1, tzinfo=UTC),
    )
    validate_event_envelope(event)
    assert event["domain"] == "education"


def test_planning_service_agent_id_allowed():
    event = build_event(
        family_id=2,
        domain="planning",
        event_type="plan.created",
        actor={"actor_type": "user", "actor_id": "admin@example.com"},
        subject={"subject_type": "plan", "subject_id": "plan-1"},
        payload={"plan_id": "plan-1", "entity_type": "plan"},
        source={"agent_id": "PlanningService", "runtime": "backend"},
        privacy=make_privacy(contains_pii=True),
        occurred_at=datetime(2026, 3, 22, 12, 0, tzinfo=UTC),
        recorded_at=datetime(2026, 3, 22, 12, 1, tzinfo=UTC),
    )
    validate_event_envelope(event)
    assert event["domain"] == "planning"


def test_question_and_family_service_agent_ids_allowed():
    question = build_event(
        family_id=2,
        domain="question",
        event_type="question.created",
        actor={"actor_type": "user", "actor_id": "admin@example.com"},
        subject={"subject_type": "question", "subject_id": "question-1"},
        payload={"question_id": "question-1"},
        source={"agent_id": "QuestionService", "runtime": "backend"},
        privacy=make_privacy(contains_free_text=True),
        occurred_at=datetime(2026, 3, 23, 12, 0, tzinfo=UTC),
        recorded_at=datetime(2026, 3, 23, 12, 1, tzinfo=UTC),
    )
    family = build_event(
        family_id=2,
        domain="family",
        event_type="family_feature.updated",
        actor={"actor_type": "user", "actor_id": "admin@example.com"},
        subject={"subject_type": "family_feature", "subject_id": "family-2:planning"},
        payload={"feature_key": "planning"},
        source={"agent_id": "FamilyService", "runtime": "backend"},
        privacy=make_privacy(),
        occurred_at=datetime(2026, 3, 23, 12, 0, tzinfo=UTC),
        recorded_at=datetime(2026, 3, 23, 12, 1, tzinfo=UTC),
    )
    validate_event_envelope(question)
    validate_event_envelope(family)


def test_payload_snippet_and_diff_helpers():
    assert snippet_fields("prompt", "  This is a long enough prompt.  ") == {
        "prompt_snippet": "This is a long enough prompt.",
        "prompt_char_count": 29,
    }
    assert diff_field_paths(
        {"status": "draft", "nested": {"pace": "slow"}},
        {"status": "active", "nested": {"pace": "steady"}},
    ) == ["nested.pace", "status"]


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


def test_privacy_enum_validation():
    privacy = make_privacy(classification="family", export_policy="anonymizable")
    assert privacy["classification"] == "family"
    assert privacy["export_policy"] == "anonymizable"

    with pytest.raises(Exception):
        make_privacy(classification="internal")
