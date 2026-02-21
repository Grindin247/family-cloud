from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from agents.decision_agent.agent import DecisionAgent
from agents.decision_agent.schemas import DecisionActionPlan, DecisionIntakeRequest, PlannedOperation


@dataclass
class _FakeAi:
    plan: DecisionActionPlan

    def plan_actions(self, *, message: str, family_id: int, context: dict[str, Any]) -> DecisionActionPlan:
        return self.plan


@dataclass
class _FakeTools:
    sessions: dict[str, dict[str, Any]] = field(default_factory=dict)
    commit_payload: list[dict[str, Any]] = field(default_factory=list)
    commit_payload_sequence: list[list[dict[str, Any]]] = field(default_factory=list)
    goals: list[dict[str, Any]] = field(default_factory=list)
    decisions: list[dict[str, Any]] = field(default_factory=list)
    roadmap: list[dict[str, Any]] = field(default_factory=list)
    budget: dict[str, Any] = field(default_factory=dict)
    proposed_operations: list[list[PlannedOperation]] = field(default_factory=list)
    canceled: bool = False
    confirmed: bool = False

    def list_families(self, *, actor_email: str | None = None) -> list[dict[str, Any]]:
        return [{"id": 1, "name": "Home"}]

    def list_family_members(self, family_id: int, *, actor_email: str | None = None) -> list[dict[str, Any]]:
        return [{"id": 10, "email": "a@example.com", "display_name": "A", "role": "editor"}]

    def get_family_goals(self, family_id: int, *, actor_email: str | None = None) -> list[dict[str, Any]]:
        return self.goals

    def list_decisions(self, family_id: int, *, include_scores: bool = False, actor_email: str | None = None) -> list[dict[str, Any]]:
        return self.decisions

    def list_roadmap_items(self, family_id: int, *, actor_email: str | None = None) -> list[dict[str, Any]]:
        return self.roadmap

    def get_budget_summary(self, family_id: int, *, actor_email: str | None = None) -> dict[str, Any]:
        return self.budget

    def get_agent_session(self, family_id: int, agent_name: str, session_id: str, *, actor_email: str | None = None) -> dict[str, Any] | None:
        return {"state": self.sessions.get(session_id, {})}

    def put_agent_session(
        self,
        family_id: int,
        agent_name: str,
        session_id: str,
        *,
        state: dict[str, Any],
        status: str | None = None,
        actor_email: str | None = None,
    ) -> dict[str, Any] | None:
        self.sessions[session_id] = state
        return {"ok": True}

    def propose_changes(
        self,
        *,
        actor_id: str,
        actor_name: str | None,
        rationale: str,
        operations: list[PlannedOperation],
        allow_destructive: bool = False,
    ) -> dict[str, Any]:
        self.proposed_operations.append(operations)
        return {"id": "proposal-1", "status": "proposed"}

    def confirm_proposal(self, proposal_id: str, *, actor_id: str) -> dict[str, Any]:
        self.confirmed = True
        return {"id": proposal_id, "status": "confirmed"}

    def commit_proposal(self, proposal_id: str, *, actor_email: str | None = None) -> dict[str, Any]:
        if self.commit_payload_sequence:
            payload = self.commit_payload_sequence.pop(0)
            return {"id": proposal_id, "status": "committed", "commit_results": payload}
        return {"id": proposal_id, "status": "committed", "commit_results": self.commit_payload}

    def cancel_proposal(self, proposal_id: str, *, actor_id: str) -> dict[str, Any]:
        self.canceled = True
        return {"id": proposal_id, "status": "canceled"}


@dataclass
class _ErrorTools(_FakeTools):
    def propose_changes(
        self,
        *,
        actor_id: str,
        actor_name: str | None,
        rationale: str,
        operations: list[PlannedOperation],
        allow_destructive: bool = False,
    ) -> dict[str, Any]:
        raise ValueError("simulated proposal failure")


@dataclass
class _DeleteErrorTools(_FakeTools):
    def propose_changes(
        self,
        *,
        actor_id: str,
        actor_name: str | None,
        rationale: str,
        operations: list[PlannedOperation],
        allow_destructive: bool = False,
    ) -> dict[str, Any]:
        if operations and operations[0].type == "delete_goal":
            raise ValueError("simulated delete proposal failure")
        return super().propose_changes(
            actor_id=actor_id,
            actor_name=actor_name,
            rationale=rationale,
            operations=operations,
            allow_destructive=allow_destructive,
        )


def test_non_destructive_plan_auto_executes():
    tools = _FakeTools(
        commit_payload=[
            {"type": "update_goal", "payload": {"goal_id": 42, "name": "Updated"}, "ok": True, "result": {"id": 42}, "error": None}
        ]
    )
    ai = _FakeAi(
        DecisionActionPlan(
            intent_summary="Update a goal",
            operations=[PlannedOperation(type="update_goal", payload={"goal_id": 42, "name": "Updated"}, reason="user asked")],
            confidence=0.9,
            missing_info=[],
            assumptions=[],
        )
    )
    agent = DecisionAgent(ai=ai, tools=tools)
    res = agent.run(DecisionIntakeRequest(message="rename goal 42", actor="u@example.com", family_id=1, session_id="s1"))
    assert res.status == "executed"
    assert len(res.execution.executed_operations) == 1
    assert not res.pending_confirmation.required


def test_delete_plan_requires_confirmation():
    tools = _FakeTools()
    ai = _FakeAi(
        DecisionActionPlan(
            intent_summary="Delete goal",
            operations=[PlannedOperation(type="delete_goal", payload={"goal_id": 12}, reason="explicit delete request")],
            confidence=0.95,
            missing_info=[],
            assumptions=[],
        )
    )
    agent = DecisionAgent(ai=ai, tools=tools)
    res = agent.run(DecisionIntakeRequest(message="delete goal 12", actor="u@example.com", family_id=1, session_id="s2"))
    assert res.status == "pending_confirmation"
    assert res.pending_confirmation.required
    assert res.pending_confirmation.proposal_id == "proposal-1"


def test_pending_delete_confirm_and_cancel_paths():
    tools = _FakeTools(
        sessions={
            "s3": {
                "pending_proposal_id": "proposal-1",
                "pending_operations": [{"type": "delete_goal", "payload": {"goal_id": 9}, "reason": "cleanup"}],
                "pending_expires_at": None,
                "last_execution_summary": {},
            }
        },
        commit_payload=[
            {"type": "delete_goal", "payload": {"goal_id": 9}, "ok": True, "result": None, "error": None},
        ],
    )
    ai = _FakeAi(DecisionActionPlan(intent_summary="noop", operations=[], confidence=1.0, missing_info=[], assumptions=[]))
    agent = DecisionAgent(ai=ai, tools=tools)

    confirmed = agent.run(DecisionIntakeRequest(message="yes, do it", actor="u@example.com", family_id=1, session_id="s3"))
    assert confirmed.status == "executed"
    assert tools.confirmed
    assert len(confirmed.execution.executed_operations) == 1

    tools.sessions["s4"] = {
        "pending_proposal_id": "proposal-2",
        "pending_operations": [{"type": "delete_goal", "payload": {"goal_id": 3}, "reason": "cleanup"}],
        "pending_expires_at": None,
        "last_execution_summary": {},
    }
    canceled = agent.run(DecisionIntakeRequest(message="cancel", actor="u@example.com", family_id=1, session_id="s4"))
    assert canceled.status == "executed"
    assert tools.canceled


def test_incomplete_score_operation_returns_needs_input():
    tools = _FakeTools()
    ai = _FakeAi(
        DecisionActionPlan(
            intent_summary="Score decision",
            operations=[PlannedOperation(type="score_decision", payload={"decision_id": 99}, reason="score it")],
            confidence=0.9,
            missing_info=[],
            assumptions=[],
        )
    )
    agent = DecisionAgent(ai=ai, tools=tools)
    res = agent.run(DecisionIntakeRequest(message="score decision 99", actor="u@example.com", family_id=1, session_id="s5"))
    assert res.status == "needs_input"
    assert res.plan is not None
    assert not res.plan.operations
    assert any("goals" in item.lower() or "score_decision" in item for item in res.plan.missing_info)


def test_score_operation_backfills_goal_scores_from_goals_context():
    tools = _FakeTools(
        goals=[
            {"id": 11, "name": "Financial Stability", "weight": 0.7},
            {"id": 12, "name": "Family Time", "weight": 0.3},
        ],
        commit_payload=[
            {"type": "score_decision", "payload": {"decision_id": 99}, "ok": True, "result": {"decision_id": 99}, "error": None}
        ],
    )
    ai = _FakeAi(
        DecisionActionPlan(
            intent_summary="Score decision",
            operations=[PlannedOperation(type="score_decision", payload={"decision_id": 99}, reason="score it")],
            confidence=0.9,
            missing_info=[],
            assumptions=[],
        )
    )
    agent = DecisionAgent(ai=ai, tools=tools)
    res = agent.run(DecisionIntakeRequest(message="score decision 99", actor="u@example.com", family_id=1, session_id="s8"))
    assert res.status == "executed"
    assert tools.proposed_operations
    score_payload = tools.proposed_operations[0][0].payload
    assert "goal_scores" in score_payload
    assert len(score_payload["goal_scores"]) == 2
    assert not any("missing required field" in item for item in (res.plan.missing_info if res.plan else []))


def test_create_decision_is_auto_scored_when_goals_exist():
    tools = _FakeTools(
        goals=[{"id": 11, "name": "Financial Stability", "weight": 1.0}],
        commit_payload_sequence=[
            [
                {
                    "type": "create_decision",
                    "payload": {"family_id": 1, "title": "Buy SUV", "description": "Large SUV purchase"},
                    "ok": True,
                    "result": {"id": 55},
                    "error": None,
                }
            ],
            [
                {
                    "type": "score_decision",
                    "payload": {"decision_id": 55},
                    "ok": True,
                    "result": {"decision_id": 55, "weighted_total_1_to_5": 3.0, "threshold_1_to_5": 4.0},
                    "error": None,
                }
            ],
        ],
    )
    ai = _FakeAi(
        DecisionActionPlan(
            intent_summary="Capture decision",
            operations=[
                PlannedOperation(
                    type="create_decision",
                    payload={"family_id": 1, "title": "Buy SUV", "description": "Large SUV purchase"},
                    reason="capture draft",
                )
            ],
            confidence=0.9,
            missing_info=[],
            assumptions=[],
        )
    )
    agent = DecisionAgent(ai=ai, tools=tools)
    res = agent.run(DecisionIntakeRequest(message="Score the decision to buy a new large SUV", actor="u@example.com", family_id=1, session_id="s9"))
    assert res.status == "executed"
    assert len(tools.proposed_operations) == 2
    assert tools.proposed_operations[1][0].type == "score_decision"
    assert tools.proposed_operations[1][0].payload["decision_id"] == 55


def test_create_decision_notes_include_assumptions_and_missing_info():
    tools = _FakeTools(
        commit_payload=[
            {
                "type": "create_decision",
                "payload": {"family_id": 1, "title": "Plan purchase", "description": "Considering purchase"},
                "ok": True,
                "result": {"id": 88},
                "error": None,
            }
        ]
    )
    ai = _FakeAi(
        DecisionActionPlan(
            intent_summary="Capture purchase decision",
            operations=[PlannedOperation(type="create_decision", payload={"family_id": 1, "title": "Plan purchase", "description": "Considering purchase"}, reason="capture")],
            confidence=0.9,
            missing_info=["Need estimated cost range."],
            assumptions=["Assume target date is next month."],
        )
    )
    agent = DecisionAgent(ai=ai, tools=tools)
    res = agent.run(DecisionIntakeRequest(message="Should we buy it?", actor="u@example.com", family_id=1, session_id="s10"))
    assert res.status == "executed"
    create_payload = tools.proposed_operations[0][0].payload
    notes = create_payload.get("notes", "")
    assert "Decision Agent Context" in notes
    assert "Assumptions:" in notes
    assert "Missing Information:" in notes
    assert "Need estimated cost range." in notes


def test_update_decision_notes_append_to_existing_user_notes():
    tools = _FakeTools(
        decisions=[{"id": 77, "title": "School move", "description": "Decision", "notes": "Keep this user note."}],
        commit_payload=[
            {"type": "update_decision", "payload": {"decision_id": 77}, "ok": True, "result": {"id": 77}, "error": None}
        ],
    )
    ai = _FakeAi(
        DecisionActionPlan(
            intent_summary="Refine decision",
            operations=[PlannedOperation(type="update_decision", payload={"decision_id": 77, "title": "School move 2026"}, reason="refine")],
            confidence=0.8,
            missing_info=["Need transport constraints."],
            assumptions=["Assume current school year ends in June."],
        )
    )
    agent = DecisionAgent(ai=ai, tools=tools)
    res = agent.run(DecisionIntakeRequest(message="update decision 77", actor="u@example.com", family_id=1, session_id="s11"))
    assert res.status == "executed"
    update_payload = tools.proposed_operations[0][0].payload
    notes = update_payload.get("notes", "")
    assert notes.startswith("Keep this user note.")
    assert "Decision Agent Context" in notes
    assert "Need transport constraints." in notes


def test_empty_assumptions_and_missing_info_do_not_change_notes():
    tools = _FakeTools(
        decisions=[{"id": 78, "title": "Decision", "description": "Decision", "notes": "Existing note"}],
        commit_payload=[
            {"type": "update_decision", "payload": {"decision_id": 78}, "ok": True, "result": {"id": 78}, "error": None}
        ],
    )
    ai = _FakeAi(
        DecisionActionPlan(
            intent_summary="Minor edit",
            operations=[PlannedOperation(type="update_decision", payload={"decision_id": 78, "title": "Decision v2"}, reason="edit")],
            confidence=0.7,
            missing_info=[],
            assumptions=[],
        )
    )
    agent = DecisionAgent(ai=ai, tools=tools)
    res = agent.run(DecisionIntakeRequest(message="rename decision 78", actor="u@example.com", family_id=1, session_id="s12"))
    assert res.status == "executed"
    update_payload = tools.proposed_operations[0][0].payload
    assert "notes" not in update_payload


def test_score_missing_details_append_missing_info_to_update_notes():
    tools = _FakeTools(
        goals=[],
        decisions=[{"id": 99, "title": "Buy SUV", "description": "Purchase", "notes": "Original note"}],
        commit_payload=[
            {"type": "update_decision", "payload": {"decision_id": 99}, "ok": True, "result": {"id": 99}, "error": None}
        ],
    )
    ai = _FakeAi(
        DecisionActionPlan(
            intent_summary="Score and annotate decision",
            operations=[
                PlannedOperation(type="update_decision", payload={"decision_id": 99}, reason="annotate"),
                PlannedOperation(type="score_decision", payload={"decision_id": 99}, reason="score"),
            ],
            confidence=0.9,
            missing_info=[],
            assumptions=[],
        )
    )
    agent = DecisionAgent(ai=ai, tools=tools)
    res = agent.run(DecisionIntakeRequest(message="score decision 99", actor="u@example.com", family_id=1, session_id="s13"))
    assert res.status == "executed"
    update_payload = tools.proposed_operations[0][0].payload
    notes = update_payload.get("notes", "")
    assert "Missing Information:" in notes
    assert "No family goals configured yet" in notes


def test_duplicate_context_block_not_appended_within_same_minute():
    fixed_now = datetime(2026, 2, 21, 12, 34, 10, tzinfo=timezone.utc)

    class _FixedTimeAgent(DecisionAgent):
        def _utcnow(self) -> datetime:
            return fixed_now

    tools = _FakeTools(
        decisions=[{"id": 100, "title": "Move", "description": "Move decision", "notes": ""}],
        commit_payload=[
            {"type": "update_decision", "payload": {"decision_id": 100}, "ok": True, "result": {"id": 100}, "error": None}
        ],
    )
    ai = _FakeAi(
        DecisionActionPlan(
            intent_summary="Refine move decision",
            operations=[PlannedOperation(type="update_decision", payload={"decision_id": 100}, reason="refine")],
            confidence=0.8,
            missing_info=["Need moving budget."],
            assumptions=["Assume move in summer."],
        )
    )
    agent = _FixedTimeAgent(ai=ai, tools=tools)
    first = agent.run(DecisionIntakeRequest(message="update decision 100", actor="u@example.com", family_id=1, session_id="s14"))
    assert first.status == "executed"
    first_notes = tools.proposed_operations[0][0].payload.get("notes", "")
    tools.proposed_operations.clear()
    tools.decisions = [{"id": 100, "title": "Move", "description": "Move decision", "notes": first_notes}]

    second = agent.run(DecisionIntakeRequest(message="update decision 100", actor="u@example.com", family_id=1, session_id="s15"))
    assert second.status == "executed"
    second_notes = tools.proposed_operations[0][0].payload.get("notes", "")
    assert second_notes.count("Decision Agent Context") == 1


def test_notes_context_block_is_truncated_when_too_large():
    very_long_missing = ["x" * 4000]
    tools = _FakeTools(
        commit_payload=[
            {"type": "create_decision", "payload": {"family_id": 1}, "ok": True, "result": {"id": 101}, "error": None}
        ]
    )
    ai = _FakeAi(
        DecisionActionPlan(
            intent_summary="Create oversized context",
            operations=[PlannedOperation(type="create_decision", payload={"family_id": 1, "title": "Big", "description": "Big"}, reason="create")],
            confidence=0.6,
            missing_info=very_long_missing,
            assumptions=[],
        )
    )
    agent = DecisionAgent(ai=ai, tools=tools)
    res = agent.run(DecisionIntakeRequest(message="create decision", actor="u@example.com", family_id=1, session_id="s16"))
    assert res.status == "executed"
    notes = tools.proposed_operations[0][0].payload.get("notes", "")
    assert "... [truncated]" in notes


def test_update_roadmap_item_resolves_roadmap_id_from_alias():
    tools = _FakeTools(
        commit_payload=[
            {"type": "update_roadmap_item", "payload": {"roadmap_id": 42}, "ok": True, "result": {"id": 42}, "error": None}
        ]
    )
    ai = _FakeAi(
        DecisionActionPlan(
            intent_summary="Update roadmap",
            operations=[PlannedOperation(type="update_roadmap_item", payload={"item_id": 42, "status": "In-Progress"}, reason="status update")],
            confidence=0.8,
            missing_info=[],
            assumptions=[],
        )
    )
    agent = DecisionAgent(ai=ai, tools=tools)
    res = agent.run(DecisionIntakeRequest(message="update roadmap item 42", actor="u@example.com", family_id=1, session_id="s17"))
    assert res.status == "executed"
    payload = tools.proposed_operations[0][0].payload
    assert payload.get("roadmap_id") == 42


def test_update_roadmap_item_resolves_roadmap_id_from_single_decision_match():
    tools = _FakeTools(
        commit_payload=[
            {"type": "update_roadmap_item", "payload": {"roadmap_id": 501}, "ok": True, "result": {"id": 501}, "error": None}
        ],
    )
    tools.list_roadmap_items = lambda family_id, actor_email=None: [  # type: ignore[method-assign]
        {"id": 500, "decision_id": 9, "bucket": "2026-Q2", "status": "Scheduled"},
        {"id": 501, "decision_id": 88, "bucket": "2026-Q3", "status": "Scheduled"},
    ]
    ai = _FakeAi(
        DecisionActionPlan(
            intent_summary="Update roadmap by decision id",
            operations=[PlannedOperation(type="update_roadmap_item", payload={"decision_id": 88, "status": "In-Progress"}, reason="advance status")],
            confidence=0.85,
            missing_info=[],
            assumptions=[],
        )
    )
    agent = DecisionAgent(ai=ai, tools=tools)
    res = agent.run(DecisionIntakeRequest(message="set roadmap for decision 88 to in progress", actor="u@example.com", family_id=1, session_id="s18"))
    assert res.status == "executed"
    payload = tools.proposed_operations[0][0].payload
    assert payload.get("roadmap_id") == 501


def test_update_roadmap_item_missing_roadmap_id_when_ambiguous():
    tools = _FakeTools()
    tools.list_roadmap_items = lambda family_id, actor_email=None: [  # type: ignore[method-assign]
        {"id": 11, "decision_id": 77, "bucket": "Next", "status": "Scheduled"},
        {"id": 12, "decision_id": 78, "bucket": "Next", "status": "Scheduled"},
    ]
    ai = _FakeAi(
        DecisionActionPlan(
            intent_summary="Ambiguous roadmap update",
            operations=[PlannedOperation(type="update_roadmap_item", payload={"status": "Done"}, reason="close item")],
            confidence=0.6,
            missing_info=[],
            assumptions=[],
        )
    )
    agent = DecisionAgent(ai=ai, tools=tools)
    res = agent.run(DecisionIntakeRequest(message="mark roadmap item done", actor="u@example.com", family_id=1, session_id="s19"))
    assert res.status == "needs_input"
    assert res.plan is not None
    assert any("update_roadmap_item missing required field(s): roadmap_id" in item for item in res.plan.missing_info)


def test_execution_error_is_returned_as_failed_operation():
    tools = _ErrorTools()
    ai = _FakeAi(
        DecisionActionPlan(
            intent_summary="Update a goal",
            operations=[PlannedOperation(type="update_goal", payload={"goal_id": 42, "name": "Updated"}, reason="user asked")],
            confidence=0.9,
            missing_info=[],
            assumptions=[],
        )
    )
    agent = DecisionAgent(ai=ai, tools=tools)
    res = agent.run(DecisionIntakeRequest(message="rename goal 42", actor="u@example.com", family_id=1, session_id="s6"))
    assert res.status == "failed"
    assert not res.execution.executed_operations
    assert len(res.execution.failed_operations) == 1
    assert "simulated proposal failure" in (res.execution.failed_operations[0].error or "")


def test_destructive_proposal_error_is_returned_as_failed_operation():
    tools = _DeleteErrorTools()
    ai = _FakeAi(
        DecisionActionPlan(
            intent_summary="Delete goal",
            operations=[PlannedOperation(type="delete_goal", payload={"goal_id": 42}, reason="user asked")],
            confidence=0.9,
            missing_info=[],
            assumptions=[],
        )
    )
    agent = DecisionAgent(ai=ai, tools=tools)
    res = agent.run(DecisionIntakeRequest(message="delete goal 42", actor="u@example.com", family_id=1, session_id="s7"))
    assert res.status == "failed"
    assert not res.pending_confirmation.required
    assert not res.execution.executed_operations
    assert len(res.execution.failed_operations) == 1
    assert "simulated delete proposal failure" in (res.execution.failed_operations[0].error or "")


def test_summary_only_roadmap_request_returns_structured_summary():
    tools = _FakeTools(
        decisions=[
            {
                "id": 200,
                "title": "Homeschool plan",
                "status": "Queued",
                "urgency": 4,
                "target_date": None,
                "score_summary": {"weighted_total_1_to_5": 4.3},
            }
        ],
        roadmap=[
            {
                "id": 900,
                "decision_id": 200,
                "bucket": "2026-Q3",
                "status": "Scheduled",
                "start_date": None,
                "end_date": None,
                "dependencies": [1, 2],
            }
        ],
    )
    ai = _FakeAi(DecisionActionPlan(intent_summary="Roadmap summary", operations=[], confidence=1.0, missing_info=[], assumptions=[]))
    agent = DecisionAgent(ai=ai, tools=tools)
    res = agent.run(DecisionIntakeRequest(message="What decisions are currently on my roadmap?", actor="u@example.com", family_id=1, session_id="s20"))
    assert res.summary is not None
    assert res.summary.roadmap is not None
    assert res.summary.decisions is not None
    assert res.summary.roadmap.total == 1
    assert res.summary.roadmap.items[0].decision_title == "Homeschool plan"


def test_summary_multi_domain_budget_includes_related_roadmap():
    tools = _FakeTools(
        roadmap=[{"id": 901, "decision_id": 201, "bucket": "Now", "status": "In-Progress", "dependencies": []}],
        budget={
            "threshold_1_to_5": 4.0,
            "period_start_date": "2026-02-01",
            "period_end_date": "2026-02-28",
            "default_allowance": 2,
            "members": [{"member_id": 11, "display_name": "A", "allowance": 2, "used": 1, "remaining": 1}],
        },
    )
    ai = _FakeAi(DecisionActionPlan(intent_summary="Budget summary", operations=[], confidence=1.0, missing_info=[], assumptions=[]))
    agent = DecisionAgent(ai=ai, tools=tools)
    res = agent.run(DecisionIntakeRequest(message="Summarize our budget and discretionary allowance", actor="u@example.com", family_id=1, session_id="s21"))
    assert res.summary is not None
    assert res.summary.budget is not None
    assert res.summary.roadmap is not None
    assert res.summary.budget.members[0].remaining == 1


def test_summary_mixed_mode_with_write_operation():
    tools = _FakeTools(
        commit_payload=[{"type": "update_goal", "payload": {"goal_id": 42}, "ok": True, "result": {"id": 42}, "error": None}],
        goals=[{"id": 9, "name": "Stability", "weight": 0.8, "active": True}],
        decisions=[{"id": 202, "title": "Stay-at-home parent", "status": "Queued", "urgency": 3, "target_date": None, "score_summary": None}],
    )
    ai = _FakeAi(
        DecisionActionPlan(
            intent_summary="Update and summarize",
            operations=[PlannedOperation(type="update_goal", payload={"goal_id": 42, "name": "Updated"}, reason="user asked")],
            confidence=0.9,
            missing_info=[],
            assumptions=[],
        )
    )
    agent = DecisionAgent(ai=ai, tools=tools)
    res = agent.run(DecisionIntakeRequest(message="Update goal 42 and summarize current decisions", actor="u@example.com", family_id=1, session_id="s22"))
    assert res.status == "executed"
    assert res.summary is not None
    assert res.summary.decisions is not None
    assert len(res.execution.executed_operations) == 1


def test_summary_present_when_pending_confirmation():
    tools = _FakeTools(decisions=[{"id": 203, "title": "Delete me", "status": "Needs-Work", "urgency": None, "target_date": None, "score_summary": None}])
    ai = _FakeAi(
        DecisionActionPlan(
            intent_summary="Delete goal and summarize",
            operations=[PlannedOperation(type="delete_goal", payload={"goal_id": 12}, reason="explicit delete request")],
            confidence=0.95,
            missing_info=[],
            assumptions=[],
        )
    )
    agent = DecisionAgent(ai=ai, tools=tools)
    res = agent.run(DecisionIntakeRequest(message="Delete goal 12 and show a summary of decisions", actor="u@example.com", family_id=1, session_id="s23"))
    assert res.status == "pending_confirmation"
    assert res.summary is not None
    assert res.summary.decisions is not None


def test_summary_absent_when_not_requested():
    tools = _FakeTools(commit_payload=[{"type": "update_goal", "payload": {"goal_id": 7}, "ok": True, "result": {"id": 7}, "error": None}])
    ai = _FakeAi(
        DecisionActionPlan(
            intent_summary="Update goal",
            operations=[PlannedOperation(type="update_goal", payload={"goal_id": 7, "name": "A"}, reason="update")],
            confidence=0.8,
            missing_info=[],
            assumptions=[],
        )
    )
    agent = DecisionAgent(ai=ai, tools=tools)
    res = agent.run(DecisionIntakeRequest(message="rename goal 7 to A", actor="u@example.com", family_id=1, session_id="s24"))
    assert res.summary is None


def test_summary_item_caps_applied():
    decisions = [
        {"id": i, "title": f"Decision {i}", "status": "Queued", "urgency": 3, "target_date": None, "score_summary": None}
        for i in range(1, 16)
    ]
    roadmap = [
        {"id": i, "decision_id": i, "bucket": "2026-Q3", "status": "Scheduled", "start_date": None, "end_date": None, "dependencies": []}
        for i in range(1, 16)
    ]
    tools = _FakeTools(decisions=decisions, roadmap=roadmap)
    ai = _FakeAi(DecisionActionPlan(intent_summary="Roadmap summary", operations=[], confidence=1.0, missing_info=[], assumptions=[]))
    agent = DecisionAgent(ai=ai, tools=tools)
    res = agent.run(DecisionIntakeRequest(message="Summarize roadmap timeline", actor="u@example.com", family_id=1, session_id="s25"))
    assert res.summary is not None
    assert res.summary.roadmap is not None
    assert res.summary.decisions is not None
    assert res.summary.roadmap.total == 15
    assert len(res.summary.roadmap.items) == 10
    assert res.summary.decisions.total == 15
    assert len(res.summary.decisions.items) == 10
