from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import hashlib
import re
from typing import Any

from agents.common.events import EventPublisher, Subjects
from agents.common.observability import new_correlation_id
from agents.common.settings import settings

from .ai import DecisionAi
from .schemas import (
    AgentSummary,
    BudgetMemberSnapshot,
    BudgetSummarySnapshot,
    DecisionSummaryItem,
    DecisionsSummary,
    DecisionActionPlan,
    DecisionAgentResponse,
    DecisionDraft,
    DecisionExecution,
    DecisionExplanation,
    ExecutionOperationResult,
    GoalSummaryItem,
    GoalsSummary,
    PendingConfirmation,
    PlannedOperation,
    DecisionIntakeRequest,
    RoadmapSummary,
    RoadmapSummaryItem,
    SummaryDomain,
)
from .tools import decision_tools


_DELETE_TYPES = {"delete_family", "delete_member", "delete_goal", "delete_decision", "delete_roadmap_item"}
_NOTES_BLOCK_MAX_CHARS = 1600
_NOTES_TRUNCATION_MARKER = "... [truncated]"
MAX_SUMMARY_ITEMS_PER_DOMAIN = 10
_SUMMARY_KEYWORDS: dict[SummaryDomain, tuple[str, ...]] = {
    "roadmap": ("roadmap", "schedule", "timeline", "on my roadmap"),
    "decisions": ("decision", "decisions", "queued", "needs-work", "scored"),
    "goals": ("goal", "goals", "priorities", "weights"),
    "budget": ("budget", "allowance", "threshold", "discretionary"),
}
_SUMMARY_RELATED_DOMAINS: dict[SummaryDomain, tuple[SummaryDomain, ...]] = {
    "roadmap": ("decisions",),
    "decisions": ("roadmap",),
    "goals": ("decisions",),
    "budget": ("roadmap",),
}
_REQUIRED_FIELDS_BY_TYPE: dict[str, tuple[str, ...]] = {
    "create_family": ("name",),
    "update_family": ("family_id", "name"),
    "delete_family": ("family_id",),
    "create_member": ("family_id", "email", "display_name", "role"),
    "update_member": ("family_id", "member_id"),
    "delete_member": ("family_id", "member_id"),
    "create_goal": ("family_id", "name", "description", "weight"),
    "update_goal": ("goal_id",),
    "delete_goal": ("goal_id",),
    "create_decision": ("family_id", "title", "description"),
    "update_decision": ("decision_id",),
    "delete_decision": ("decision_id",),
    "score_decision": ("decision_id", "goal_scores", "threshold_1_to_5"),
    "create_roadmap_item": ("decision_id", "bucket", "status"),
    "update_roadmap_item": ("roadmap_id",),
    "delete_roadmap_item": ("roadmap_id",),
    "update_budget_policy": ("family_id", "threshold_1_to_5", "period_days", "default_allowance"),
    "reset_budget_period": ("family_id",),
}


@dataclass
class SummaryRequest:
    requested_domains: list[SummaryDomain]
    included_domains: list[SummaryDomain]

    @property
    def enabled(self) -> bool:
        return bool(self.requested_domains)


@dataclass
class DecisionAgent:
    name: str = "decision"
    ai: DecisionAi | None = None
    tools: object | None = None

    def run(self, req: DecisionIntakeRequest) -> DecisionAgentResponse:
        cid = new_correlation_id()
        tools = self.tools or decision_tools()
        ai = self.ai or DecisionAi()
        publisher = EventPublisher()
        session_id = (req.session_id or "default").strip() or "default"
        actor = req.actor.strip()
        msg = req.message.strip()
        summary_request = self._detect_summary_request(msg)

        session = self._load_session(tools, req.family_id, session_id, actor)
        pending = self._pending_state(session)

        # Confirmation/cancel path has priority whenever a destructive proposal is pending.
        if pending:
            response = self._handle_pending_confirmation(
                tools,
                req,
                session_id,
                pending,
                msg,
                publisher,
                cid,
                summary_request=summary_request,
            )
            if response is not None:
                return response

        context = self._build_context(tools, req.family_id, actor)
        plan: DecisionActionPlan = ai.plan_actions(message=msg, family_id=req.family_id, context=context)
        prepared_ops, prep_missing = self._prepare_operations(plan.operations, context)
        plan = plan.model_copy(update={"operations": prepared_ops, "missing_info": [*plan.missing_info, *prep_missing]})
        plan = plan.model_copy(update={"operations": self._decorate_decision_notes(plan, context)})
        self._audit(
            publisher,
            req.family_id,
            actor,
            cid,
            event="plan_created",
            extra={"intent": plan.intent_summary, "operation_count": len(plan.operations), "confidence": plan.confidence},
        )

        if plan.missing_info and not plan.operations:
            draft = self._fallback_draft(msg)
            summary = self._build_summary_if_requested(summary_request, context)
            if summary is not None:
                self._audit(
                    publisher,
                    req.family_id,
                    actor,
                    cid,
                    event="summary_generated",
                    extra={
                        "requested_domains": summary.requested_domains,
                        "included_domains": summary.included_domains,
                        **self._summary_counts(summary),
                    },
                )
            return self._response(
                session_id=session_id,
                status="needs_input",
                intent=plan.intent_summary,
                plan=plan,
                execution=DecisionExecution(),
                pending=PendingConfirmation(required=False),
                explanation="Need additional details before executing operations.",
                artifacts={},
                raw_tool_trace=[],
                draft=draft,
                followups=plan.missing_info,
                summary=summary,
            )

        # Shadow mode: plan only, never execute.
        if settings.decision_agent_shadow_mode:
            draft = self._fallback_draft(msg)
            summary = self._build_summary_if_requested(summary_request, context)
            if summary is not None:
                self._audit(
                    publisher,
                    req.family_id,
                    actor,
                    cid,
                    event="summary_generated",
                    extra={
                        "requested_domains": summary.requested_domains,
                        "included_domains": summary.included_domains,
                        **self._summary_counts(summary),
                    },
                )
            return self._response(
                session_id=session_id,
                status="needs_input",
                intent=plan.intent_summary,
                plan=plan,
                execution=DecisionExecution(),
                pending=PendingConfirmation(required=False),
                explanation="Shadow mode enabled; generated plan without execution.",
                artifacts={},
                raw_tool_trace=[],
                draft=draft,
                followups=[],
                summary=summary,
            )

        # Legacy mode fallback (feature flag off): keep conservative behavior by returning plan only.
        if not settings.decision_agent_autonomous_mode:
            draft = self._fallback_draft(msg)
            summary = self._build_summary_if_requested(summary_request, context)
            if summary is not None:
                self._audit(
                    publisher,
                    req.family_id,
                    actor,
                    cid,
                    event="summary_generated",
                    extra={
                        "requested_domains": summary.requested_domains,
                        "included_domains": summary.included_domains,
                        **self._summary_counts(summary),
                    },
                )
            return self._response(
                session_id=session_id,
                status="needs_input",
                intent=plan.intent_summary,
                plan=plan,
                execution=DecisionExecution(),
                pending=PendingConfirmation(required=False),
                explanation="Autonomous mode disabled; returning operation plan for manual handling.",
                artifacts={},
                raw_tool_trace=[],
                draft=draft,
                followups=[],
                summary=summary,
            )

        non_destructive = [op for op in plan.operations if op.type not in _DELETE_TYPES]
        destructive = [op for op in plan.operations if op.type in _DELETE_TYPES]

        execution = DecisionExecution()
        raw_trace: list[dict[str, Any]] = []
        artifacts: dict[str, list[int]] = {}
        runtime_followups: list[str] = []

        if non_destructive:
            try:
                exec_results, trace = self._execute_operations(
                    tools=tools,
                    actor=actor,
                    rationale=f"Autonomous execution for: {plan.intent_summary}",
                    operations=non_destructive,
                    allow_destructive=False,
                )
                raw_trace.extend(trace)
                for item in exec_results:
                    (execution.executed_operations if item.ok else execution.failed_operations).append(item)
                    _collect_artifacts(artifacts, item.result)
                auto_results, auto_trace, auto_followups = self._execute_auto_score_operations(
                    tools=tools,
                    actor=actor,
                    context=context,
                    execution=execution,
                )
                runtime_followups.extend(auto_followups)
                raw_trace.extend(auto_trace)
                for item in auto_results:
                    (execution.executed_operations if item.ok else execution.failed_operations).append(item)
                    _collect_artifacts(artifacts, item.result)
                self._audit(
                    publisher,
                    req.family_id,
                    actor,
                    cid,
                    event="plan_executed",
                    extra={
                        "executed": len([r for r in exec_results if r.ok]),
                        "failed": len([r for r in exec_results if not r.ok]),
                    },
                )
            except Exception as exc:
                for op in non_destructive:
                    execution.failed_operations.append(
                        ExecutionOperationResult(type=op.type, payload=op.payload, ok=False, result=None, error=str(exc))
                    )
                self._audit(
                    publisher,
                    req.family_id,
                    actor,
                    cid,
                    event="execution_failure",
                    extra={"error": str(exc), "operation_count": len(non_destructive)},
                )

        pending_confirmation = PendingConfirmation(required=False)
        if destructive:
            try:
                proposal = tools.propose_changes(
                    actor_id=actor,
                    actor_name=actor,
                    rationale=f"Awaiting destructive confirmation for: {plan.intent_summary}",
                    operations=destructive,
                    allow_destructive=True,
                )
                proposal_id = str(proposal["id"])
                ttl = datetime.now(timezone.utc) + timedelta(seconds=settings.decision_pending_confirmation_ttl_seconds)
                pending_state = {
                    "pending_proposal_id": proposal_id,
                    "pending_operations": [op.model_dump(mode="json") for op in destructive],
                    "pending_expires_at": ttl.isoformat(),
                    "last_execution_summary": {"executed_non_destructive": len(non_destructive), "failed_non_destructive": len(execution.failed_operations)},
                }
                self._save_session(tools, req.family_id, session_id, actor, pending_state)
                pending_confirmation = PendingConfirmation(
                    required=True,
                    proposal_id=proposal_id,
                    operations=destructive,
                    prompt="I prepared delete operations. Reply with 'confirm' to proceed or 'cancel' to abort.",
                )
                self._audit(
                    publisher,
                    req.family_id,
                    actor,
                    cid,
                    event="confirmation_requested",
                    extra={"proposal_id": proposal_id, "operation_count": len(destructive)},
                )
            except Exception as exc:
                for op in destructive:
                    execution.failed_operations.append(
                        ExecutionOperationResult(type=op.type, payload=op.payload, ok=False, result=None, error=str(exc))
                    )
                self._audit(
                    publisher,
                    req.family_id,
                    actor,
                    cid,
                    event="execution_failure",
                    extra={"error": str(exc), "operation_count": len(destructive)},
                )

        status = "pending_confirmation" if pending_confirmation.required else ("failed" if execution.failed_operations else "executed")
        if summary_request.enabled and execution.executed_operations:
            context = self._build_context(tools, req.family_id, actor)
        draft = self._fallback_draft(msg)
        explanation = self._build_execution_explanation(execution, context)
        summary = self._build_summary_if_requested(summary_request, context)
        if summary is not None:
            self._audit(
                publisher,
                req.family_id,
                actor,
                cid,
                event="summary_generated",
                extra={
                    "requested_domains": summary.requested_domains,
                    "included_domains": summary.included_domains,
                    **self._summary_counts(summary),
                },
            )
        return self._response(
            session_id=session_id,
            status=status,
            intent=plan.intent_summary,
            plan=plan,
            execution=execution,
            pending=pending_confirmation,
            explanation=explanation,
            artifacts=artifacts,
            raw_tool_trace=raw_trace,
            draft=draft,
            followups=[*plan.missing_info, *runtime_followups],
            summary=summary,
        )

    def _load_session(self, tools: Any, family_id: int, session_id: str, actor: str) -> dict[str, Any]:
        try:
            return (tools.get_agent_session(family_id, self.name, session_id, actor_email=actor) or {}).get("state") or {}
        except Exception:
            return {}

    def _pending_state(self, session: dict[str, Any]) -> dict[str, Any] | None:
        proposal_id = session.get("pending_proposal_id")
        operations = session.get("pending_operations")
        if not isinstance(proposal_id, str) or not proposal_id:
            return None
        if not isinstance(operations, list):
            return None
        return {
            "proposal_id": proposal_id,
            "operations": operations,
            "expires_at": session.get("pending_expires_at"),
            "last_execution_summary": session.get("last_execution_summary") or {},
        }

    def _handle_pending_confirmation(
        self,
        tools: Any,
        req: DecisionIntakeRequest,
        session_id: str,
        pending: dict[str, Any],
        msg: str,
        publisher: EventPublisher,
        cid: str,
        summary_request: SummaryRequest | None = None,
    ) -> DecisionAgentResponse | None:
        proposal_id = str(pending["proposal_id"])
        intent = _parse_confirmation_intent(msg)
        ops = [PlannedOperation.model_validate(op) for op in pending.get("operations", []) if isinstance(op, dict)]
        plan = DecisionActionPlan(intent_summary="Process pending destructive confirmation", operations=ops, confidence=1.0, missing_info=[], assumptions=[])
        draft = self._fallback_draft(msg)
        summary: AgentSummary | None = None
        if summary_request and summary_request.enabled:
            summary_context = self._build_context(tools, req.family_id, req.actor)
            summary = self._build_summary_if_requested(summary_request, summary_context)
            if summary is not None:
                self._audit(
                    publisher,
                    req.family_id,
                    req.actor,
                    cid,
                    event="summary_generated",
                    extra={
                        "requested_domains": summary.requested_domains,
                        "included_domains": summary.included_domains,
                        **self._summary_counts(summary),
                    },
                )

        if intent == "cancel":
            try:
                tools.cancel_proposal(proposal_id, actor_id=req.actor)
            except Exception:
                pass
            self._save_session(tools, req.family_id, session_id, req.actor, {"pending_proposal_id": None, "pending_operations": [], "pending_expires_at": None, "last_execution_summary": pending.get("last_execution_summary", {})})
            self._audit(publisher, req.family_id, req.actor, cid, event="proposal_canceled", extra={"proposal_id": proposal_id})
            if summary_request and summary_request.enabled:
                summary_context = self._build_context(tools, req.family_id, req.actor)
                summary = self._build_summary_if_requested(summary_request, summary_context)
            return self._response(
                session_id=session_id,
                status="executed",
                intent="Canceled destructive operations",
                plan=plan,
                execution=DecisionExecution(),
                pending=PendingConfirmation(required=False),
                explanation="Canceled pending delete proposal.",
                artifacts={},
                raw_tool_trace=[],
                draft=draft,
                followups=[],
                summary=summary,
            )

        if intent == "confirm":
            raw_trace: list[dict[str, Any]] = []
            execution = DecisionExecution()
            artifacts: dict[str, list[int]] = {}
            try:
                confirmed = tools.confirm_proposal(proposal_id, actor_id=req.actor)
                committed = tools.commit_proposal(proposal_id, actor_email=req.actor)
                raw_trace.append({"action": "confirm_proposal", "result": confirmed})
                raw_trace.append({"action": "commit_proposal", "result": {"id": committed.get("id"), "status": committed.get("status")}})
                for result in committed.get("commit_results", []):
                    op_res = ExecutionOperationResult(
                        type=result.get("type"),
                        payload=result.get("payload", {}),
                        ok=bool(result.get("ok")),
                        result=result.get("result"),
                        error=result.get("error"),
                    )
                    (execution.executed_operations if op_res.ok else execution.failed_operations).append(op_res)
                    _collect_artifacts(artifacts, op_res.result)
                self._save_session(
                    tools,
                    req.family_id,
                    session_id,
                    req.actor,
                    {"pending_proposal_id": None, "pending_operations": [], "pending_expires_at": None, "last_execution_summary": {"executed": len(execution.executed_operations), "failed": len(execution.failed_operations)}},
                )
                self._audit(
                    publisher,
                    req.family_id,
                    req.actor,
                    cid,
                    event="proposal_committed",
                    extra={"proposal_id": proposal_id, "executed": len(execution.executed_operations), "failed": len(execution.failed_operations)},
                )
                if summary_request and summary_request.enabled:
                    summary_context = self._build_context(tools, req.family_id, req.actor)
                    summary = self._build_summary_if_requested(summary_request, summary_context)
                return self._response(
                    session_id=session_id,
                    status="failed" if execution.failed_operations else "executed",
                    intent="Committed pending destructive operations",
                    plan=plan,
                    execution=execution,
                    pending=PendingConfirmation(required=False),
                    explanation="Confirmed and executed pending delete operations.",
                    artifacts=artifacts,
                    raw_tool_trace=raw_trace,
                    draft=draft,
                    followups=[],
                    summary=summary,
                )
            except Exception as exc:
                self._audit(
                    publisher,
                    req.family_id,
                    req.actor,
                    cid,
                    event="execution_failure",
                    extra={"proposal_id": proposal_id, "error": str(exc)},
                )
                failed = ExecutionOperationResult(
                    type=ops[0].type if ops else "delete_goal",
                    payload={},
                    ok=False,
                    result=None,
                    error=str(exc),
                )
                execution.failed_operations.append(failed)
                return self._response(
                    session_id=session_id,
                    status="failed",
                    intent="Failed to commit pending destructive operations",
                    plan=plan,
                    execution=execution,
                    pending=PendingConfirmation(required=True, proposal_id=proposal_id, operations=ops, prompt="Commit failed. Reply 'confirm' to retry or 'cancel' to abort."),
                    explanation=f"Failed to execute pending proposal: {exc}",
                    artifacts={},
                    raw_tool_trace=[],
                    draft=draft,
                    followups=[],
                    summary=summary,
                )

        # Ambiguous reply while pending delete exists.
        return self._response(
            session_id=session_id,
            status="pending_confirmation",
            intent="Awaiting destructive confirmation",
            plan=plan,
            execution=DecisionExecution(),
            pending=PendingConfirmation(
                required=True,
                proposal_id=proposal_id,
                operations=ops,
                prompt="Please reply with 'confirm' to execute deletes or 'cancel' to abort.",
            ),
            explanation="Pending delete proposal requires explicit confirmation.",
            artifacts={},
            raw_tool_trace=[],
            draft=draft,
            followups=[],
            summary=summary,
        )

    def _execute_operations(
        self,
        *,
        tools: Any,
        actor: str,
        rationale: str,
        operations: list[PlannedOperation],
        allow_destructive: bool,
    ) -> tuple[list[ExecutionOperationResult], list[dict[str, Any]]]:
        raw_trace: list[dict[str, Any]] = []
        proposal = tools.propose_changes(
            actor_id=actor,
            actor_name=actor,
            rationale=rationale,
            operations=operations,
            allow_destructive=allow_destructive,
        )
        proposal_id = str(proposal["id"])
        raw_trace.append({"action": "propose_changes", "result": proposal})
        confirmed = tools.confirm_proposal(proposal_id, actor_id=actor)
        raw_trace.append({"action": "confirm_proposal", "result": confirmed})
        committed = tools.commit_proposal(proposal_id, actor_email=actor)
        raw_trace.append({"action": "commit_proposal", "result": {"id": committed.get("id"), "status": committed.get("status")}})
        results = [
            ExecutionOperationResult(
                type=item.get("type"),
                payload=item.get("payload", {}),
                ok=bool(item.get("ok")),
                result=item.get("result"),
                error=item.get("error"),
            )
            for item in committed.get("commit_results", [])
        ]
        return results, raw_trace

    def _build_context(self, tools: Any, family_id: int, actor: str) -> dict[str, Any]:
        context: dict[str, Any] = {"family_id": family_id}
        try:
            context["families"] = tools.list_families(actor_email=actor)[:10]
        except Exception:
            context["families"] = []
        try:
            context["members"] = tools.list_family_members(family_id, actor_email=actor)[:25]
        except Exception:
            context["members"] = []
        try:
            context["goals"] = tools.get_family_goals(family_id, actor_email=actor)[:25]
        except Exception:
            context["goals"] = []
        try:
            context["decisions"] = tools.list_decisions(family_id, include_scores=True, actor_email=actor)[:50]
        except Exception:
            context["decisions"] = []
        try:
            context["roadmap"] = tools.list_roadmap_items(family_id, actor_email=actor)[:25]
        except Exception:
            context["roadmap"] = []
        try:
            context["budget"] = tools.get_budget_summary(family_id, actor_email=actor)
        except Exception:
            context["budget"] = {}
        return context

    def _prepare_operations(self, operations: list[PlannedOperation], context: dict[str, Any]) -> tuple[list[PlannedOperation], list[str]]:
        prepared: list[PlannedOperation] = []
        missing_info: list[str] = []
        for op in operations:
            normalized = self._normalize_operation(op, context)
            required = _REQUIRED_FIELDS_BY_TYPE.get(normalized.type, ())
            missing = [field for field in required if field not in normalized.payload]
            if missing:
                if normalized.type == "score_decision" and "goal_scores" in missing:
                    missing_info.append("No family goals configured yet. Add goals and weights before final decision scoring.")
                    continue
                missing_info.append(f"{normalized.type} missing required field(s): {', '.join(missing)}")
                continue
            if normalized.type == "score_decision":
                scores = normalized.payload.get("goal_scores")
                if not isinstance(scores, list) or not scores:
                    missing_info.append("score_decision requires non-empty goal_scores")
                    continue
            prepared.append(normalized)
        return prepared, missing_info

    def _decorate_decision_notes(self, plan: DecisionActionPlan, context: dict[str, Any]) -> list[PlannedOperation]:
        block = self._build_notes_context_block(
            intent=plan.intent_summary,
            assumptions=plan.assumptions,
            missing_info=plan.missing_info,
        )
        if block is None:
            return plan.operations

        decision_notes = self._decision_notes_by_id(context)
        decorated: list[PlannedOperation] = []
        for op in plan.operations:
            payload = dict(op.payload)
            if op.type == "create_decision":
                existing_notes = str(payload.get("notes") or "")
                payload["notes"] = self._append_notes_block(existing_notes, block)
            elif op.type == "update_decision":
                decision_id = payload.get("decision_id")
                payload_notes = payload.get("notes")
                base_notes = str(payload_notes) if isinstance(payload_notes, str) else decision_notes.get(decision_id, "")
                payload["notes"] = self._append_notes_block(base_notes, block)
            decorated.append(op.model_copy(update={"payload": payload}))
        return decorated

    def _normalize_operation(self, op: PlannedOperation, context: dict[str, Any]) -> PlannedOperation:
        payload = dict(op.payload)
        if op.type in ("update_roadmap_item", "delete_roadmap_item"):
            if "roadmap_id" not in payload:
                for alias in ("id", "item_id", "roadmap_item_id"):
                    value = payload.get(alias)
                    if value is not None:
                        payload["roadmap_id"] = value
                        break
            if "roadmap_id" not in payload:
                resolved = self._resolve_roadmap_id_from_context(payload, context)
                if resolved is not None:
                    payload["roadmap_id"] = resolved
        if op.type == "score_decision":
            if "goal_scores" not in payload:
                for alias in ("scores", "goal_score", "score_inputs"):
                    value = payload.get(alias)
                    if value is not None:
                        payload["goal_scores"] = value
                        break
            if "goal_scores" not in payload:
                goal_scores = self._goal_score_defaults(context)
                if goal_scores:
                    payload["goal_scores"] = goal_scores
            if "threshold_1_to_5" not in payload:
                for alias in ("threshold", "score_threshold_1_to_5"):
                    value = payload.get(alias)
                    if value is not None:
                        payload["threshold_1_to_5"] = value
                        break
                if "threshold_1_to_5" not in payload:
                    payload["threshold_1_to_5"] = self._score_threshold(context)
        return op.model_copy(update={"payload": payload})

    def _build_notes_context_block(
        self,
        *,
        intent: str,
        assumptions: list[str],
        missing_info: list[str],
    ) -> str | None:
        assumptions_clean = [item.strip() for item in assumptions if isinstance(item, str) and item.strip()]
        missing_clean = [item.strip() for item in missing_info if isinstance(item, str) and item.strip()]
        if not assumptions_clean and not missing_clean:
            return None

        now = self._utcnow().astimezone(timezone.utc)
        minute_stamp = now.strftime("%Y-%m-%dT%H:%M:00Z")
        key_source = "\n".join([intent.strip(), minute_stamp, *assumptions_clean, *missing_clean])
        dedupe_key = hashlib.sha1(key_source.encode("utf-8")).hexdigest()[:12]
        lines = [f"[Decision Agent Context | {minute_stamp} | key={dedupe_key}]", f"Intent: {intent.strip() or 'n/a'}"]
        if assumptions_clean:
            lines.append("Assumptions:")
            lines.extend([f"- {item}" for item in assumptions_clean])
        if missing_clean:
            lines.append("Missing Information:")
            lines.extend([f"- {item}" for item in missing_clean])
        lines.append("---")
        block = "\n".join(lines)
        if len(block) > _NOTES_BLOCK_MAX_CHARS:
            max_body = max(0, _NOTES_BLOCK_MAX_CHARS - len(_NOTES_TRUNCATION_MARKER) - 1)
            block = block[:max_body].rstrip() + "\n" + _NOTES_TRUNCATION_MARKER
        return block

    def _append_notes_block(self, existing_notes: str, block: str) -> str:
        key_match = re.search(r"\bkey=([0-9a-f]{12})\b", block)
        if key_match and key_match.group(0) in (existing_notes or ""):
            return existing_notes
        if not (existing_notes or "").strip():
            return block
        return existing_notes.rstrip() + "\n\n" + block

    def _decision_notes_by_id(self, context: dict[str, Any]) -> dict[int, str]:
        decisions = context.get("decisions")
        if not isinstance(decisions, list):
            return {}
        notes_by_id: dict[int, str] = {}
        for item in decisions:
            if not isinstance(item, dict):
                continue
            decision_id = item.get("id")
            if isinstance(decision_id, int):
                notes_by_id[decision_id] = str(item.get("notes") or "")
        return notes_by_id

    def _resolve_roadmap_id_from_context(self, payload: dict[str, Any], context: dict[str, Any]) -> int | None:
        roadmap = context.get("roadmap")
        if not isinstance(roadmap, list) or not roadmap:
            return None
        candidates = [item for item in roadmap if isinstance(item, dict) and isinstance(item.get("id"), int)]
        if not candidates:
            return None

        if len(candidates) == 1:
            return int(candidates[0]["id"])

        decision_id = payload.get("decision_id")
        if isinstance(decision_id, int):
            decision_matches = [item for item in candidates if item.get("decision_id") == decision_id]
            if len(decision_matches) == 1:
                return int(decision_matches[0]["id"])
            if len(decision_matches) > 1:
                return int(max(decision_matches, key=lambda item: int(item["id"]))["id"])

        bucket = payload.get("bucket")
        if isinstance(bucket, str) and bucket.strip():
            bucket_matches = [item for item in candidates if str(item.get("bucket") or "").strip().lower() == bucket.strip().lower()]
            if len(bucket_matches) == 1:
                return int(bucket_matches[0]["id"])

        return None

    def _utcnow(self) -> datetime:
        return datetime.now(timezone.utc)

    def _goal_score_defaults(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        goals = context.get("goals")
        if not isinstance(goals, list):
            return []
        defaults: list[dict[str, Any]] = []
        for goal in goals:
            if not isinstance(goal, dict):
                continue
            goal_id = goal.get("id")
            goal_name = str(goal.get("name") or "goal").strip()
            if not isinstance(goal_id, int):
                continue
            defaults.append(
                {
                    "goal_id": goal_id,
                    "score_1_to_5": 3,
                    "rationale": f"Neutral draft assumption for {goal_name}; refine with decision-specific details.",
                }
            )
        return defaults

    def _score_threshold(self, context: dict[str, Any]) -> float:
        budget = context.get("budget")
        if isinstance(budget, dict):
            threshold = budget.get("threshold_1_to_5")
            if isinstance(threshold, (int, float)):
                return float(threshold)
        return float(settings.decision_threshold_1_to_5)

    def _execute_auto_score_operations(
        self,
        *,
        tools: Any,
        actor: str,
        context: dict[str, Any],
        execution: DecisionExecution,
    ) -> tuple[list[ExecutionOperationResult], list[dict[str, Any]], list[str]]:
        scored_ids = {
            item.payload.get("decision_id")
            for item in execution.executed_operations
            if item.type == "score_decision" and isinstance(item.payload.get("decision_id"), int)
        }
        created_ids = [
            item.result.get("id")
            for item in execution.executed_operations
            if item.type == "create_decision" and isinstance(item.result, dict) and isinstance(item.result.get("id"), int)
        ]
        pending_score_ids = [decision_id for decision_id in created_ids if decision_id not in scored_ids]
        if not pending_score_ids:
            return [], [], []

        goal_scores = self._goal_score_defaults(context)
        if not goal_scores:
            return [], [], ["No family goals configured yet. Add goals and weights before final decision scoring."]

        threshold = self._score_threshold(context)
        ops = [
            PlannedOperation(
                type="score_decision",
                payload={
                    "decision_id": decision_id,
                    "goal_scores": goal_scores,
                    "threshold_1_to_5": threshold,
                    "computed_by": "ai",
                },
                reason="Auto-score newly created decision using neutral assumptions and current goal weights.",
            )
            for decision_id in pending_score_ids
        ]
        results, trace = self._execute_operations(
            tools=tools,
            actor=actor,
            rationale="Auto-score newly created decisions",
            operations=ops,
            allow_destructive=False,
        )
        return results, trace, []

    def _build_execution_explanation(self, execution: DecisionExecution, context: dict[str, Any]) -> str:
        goals = context.get("goals") if isinstance(context.get("goals"), list) else []
        goal_by_id: dict[int, dict[str, Any]] = {
            goal["id"]: goal
            for goal in goals
            if isinstance(goal, dict) and isinstance(goal.get("id"), int)
        }
        score_lines: list[str] = []
        for item in execution.executed_operations:
            if item.type != "score_decision":
                continue
            payload = item.payload if isinstance(item.payload, dict) else {}
            score_inputs = payload.get("goal_scores")
            if not isinstance(score_inputs, list) or not score_inputs:
                continue
            weighted_sum = 0.0
            total_weight = 0.0
            details: list[str] = []
            for score in score_inputs:
                if not isinstance(score, dict):
                    continue
                goal_id = score.get("goal_id")
                score_1_to_5 = score.get("score_1_to_5")
                if not isinstance(goal_id, int) or not isinstance(score_1_to_5, int):
                    continue
                goal = goal_by_id.get(goal_id, {})
                goal_name = str(goal.get("name") or f"Goal {goal_id}")
                weight = float(goal.get("weight") or 0.0)
                contribution = (score_1_to_5 / 5.0) * weight if weight > 0 else 0.0
                weighted_sum += contribution
                total_weight += weight
                details.append(f"{goal_name} w={weight:.2f} s={score_1_to_5}/5 c={contribution:.2f}")
            threshold = payload.get("threshold_1_to_5")
            threshold_value = float(threshold) if isinstance(threshold, (int, float)) else float(settings.decision_threshold_1_to_5)
            if total_weight > 0:
                weighted_1_to_5 = (weighted_sum / total_weight) * 5.0
                pass_fail = "PASS" if weighted_1_to_5 >= threshold_value else "NEEDS-WORK"
                score_lines.append(
                    f"Scored decision #{payload.get('decision_id')}: "
                    + "; ".join(details)
                    + f"; total={weighted_1_to_5:.2f}/5 vs threshold={threshold_value:.2f} => {pass_fail}."
                )
        base = "Executed non-destructive operations automatically. Delete operations require explicit confirmation."
        return base if not score_lines else base + " " + " ".join(score_lines)

    def _detect_summary_request(self, message: str) -> SummaryRequest:
        normalized = (message or "").strip().lower()
        if not normalized:
            return SummaryRequest(requested_domains=[], included_domains=[])

        looks_like_summary = any(token in normalized for token in ("summary", "summarize", "what", "show", "list", "currently"))
        requested: list[SummaryDomain] = []
        for domain, keywords in _SUMMARY_KEYWORDS.items():
            if any(keyword in normalized for keyword in keywords):
                requested.append(domain)
        if not requested or not looks_like_summary:
            return SummaryRequest(requested_domains=[], included_domains=[])

        included = self._expand_summary_domains(requested)
        return SummaryRequest(requested_domains=requested, included_domains=included)

    def _expand_summary_domains(self, requested: list[SummaryDomain]) -> list[SummaryDomain]:
        included: list[SummaryDomain] = []
        for domain in requested:
            if domain not in included:
                included.append(domain)
            for related in _SUMMARY_RELATED_DOMAINS.get(domain, ()):
                if related not in included:
                    included.append(related)
        return included

    def _build_summary_if_requested(self, summary_request: SummaryRequest, context: dict[str, Any]) -> AgentSummary | None:
        if not summary_request.enabled:
            return None
        summary = self._build_agent_summary(
            context=context,
            requested_domains=summary_request.requested_domains,
            included_domains=summary_request.included_domains,
        )
        return summary

    def _build_agent_summary(
        self,
        *,
        context: dict[str, Any],
        requested_domains: list[SummaryDomain],
        included_domains: list[SummaryDomain],
    ) -> AgentSummary:
        summary = AgentSummary(
            generated_at=self._utcnow().astimezone(timezone.utc).isoformat(),
            requested_domains=requested_domains,
            included_domains=included_domains,
        )
        if "roadmap" in included_domains:
            summary.roadmap = self._build_roadmap_summary(context)
        if "decisions" in included_domains:
            summary.decisions = self._build_decisions_summary(context)
        if "goals" in included_domains:
            summary.goals = self._build_goals_summary(context)
        if "budget" in included_domains:
            summary.budget = self._build_budget_summary(context)
        return summary

    def _build_roadmap_summary(self, context: dict[str, Any]) -> RoadmapSummary:
        roadmap = context.get("roadmap")
        items = roadmap if isinstance(roadmap, list) else []
        decisions = context.get("decisions")
        decisions_list = decisions if isinstance(decisions, list) else []
        decision_by_id = {
            int(item["id"]): item
            for item in decisions_list
            if isinstance(item, dict) and isinstance(item.get("id"), int)
        }

        by_status: dict[str, int] = {}
        by_bucket: dict[str, int] = {}
        summary_items: list[RoadmapSummaryItem] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            roadmap_id = item.get("id")
            decision_id = item.get("decision_id")
            if not isinstance(roadmap_id, int) or not isinstance(decision_id, int):
                continue
            status = str(item.get("status") or "Unknown")
            bucket = str(item.get("bucket") or "Unbucketed")
            by_status[status] = by_status.get(status, 0) + 1
            by_bucket[bucket] = by_bucket.get(bucket, 0) + 1
            if len(summary_items) >= MAX_SUMMARY_ITEMS_PER_DOMAIN:
                continue

            decision = decision_by_id.get(decision_id, {})
            score_summary = decision.get("score_summary") if isinstance(decision, dict) else None
            score_value: float | None = None
            if isinstance(score_summary, dict):
                weighted = score_summary.get("weighted_total_1_to_5")
                if isinstance(weighted, (int, float)):
                    score_value = float(weighted)
            dependencies = item.get("dependencies")
            dependencies_count = len(dependencies) if isinstance(dependencies, list) else 0
            summary_items.append(
                RoadmapSummaryItem(
                    roadmap_id=roadmap_id,
                    decision_id=decision_id,
                    decision_title=str(decision.get("title") or f"Decision #{decision_id}") if isinstance(decision, dict) else f"Decision #{decision_id}",
                    bucket=bucket,
                    status=status,
                    start_date=item.get("start_date"),
                    end_date=item.get("end_date"),
                    dependencies_count=dependencies_count,
                    decision_score_1_to_5=score_value,
                )
            )

        return RoadmapSummary(total=len([item for item in items if isinstance(item, dict)]), by_status=by_status, by_bucket=by_bucket, items=summary_items)

    def _build_decisions_summary(self, context: dict[str, Any]) -> DecisionsSummary:
        decisions = context.get("decisions")
        items = decisions if isinstance(decisions, list) else []
        by_status: dict[str, int] = {}
        scored = 0
        summary_items: list[DecisionSummaryItem] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            decision_id = item.get("id")
            if not isinstance(decision_id, int):
                continue
            status = str(item.get("status") or "Unknown")
            by_status[status] = by_status.get(status, 0) + 1
            score_summary = item.get("score_summary")
            score_value: float | None = None
            if isinstance(score_summary, dict):
                weighted = score_summary.get("weighted_total_1_to_5")
                if isinstance(weighted, (int, float)):
                    score_value = float(weighted)
                    scored += 1
            if len(summary_items) >= MAX_SUMMARY_ITEMS_PER_DOMAIN:
                continue
            summary_items.append(
                DecisionSummaryItem(
                    decision_id=decision_id,
                    title=str(item.get("title") or f"Decision #{decision_id}"),
                    status=status,
                    urgency=item.get("urgency") if isinstance(item.get("urgency"), int) else None,
                    target_date=item.get("target_date"),
                    score_1_to_5=score_value,
                )
            )
        total = len([item for item in items if isinstance(item, dict) and isinstance(item.get("id"), int)])
        return DecisionsSummary(total=total, scored=scored, unscored=max(0, total - scored), by_status=by_status, items=summary_items)

    def _build_goals_summary(self, context: dict[str, Any]) -> GoalsSummary:
        goals = context.get("goals")
        items = goals if isinstance(goals, list) else []
        summary_items: list[GoalSummaryItem] = []
        active_count = 0
        active_weight_total = 0.0
        total = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            goal_id = item.get("id")
            if not isinstance(goal_id, int):
                continue
            total += 1
            weight = float(item.get("weight") or 0.0)
            active = bool(item.get("active", False))
            if active:
                active_count += 1
                active_weight_total += weight
            if len(summary_items) >= MAX_SUMMARY_ITEMS_PER_DOMAIN:
                continue
            summary_items.append(
                GoalSummaryItem(
                    goal_id=goal_id,
                    name=str(item.get("name") or f"Goal #{goal_id}"),
                    weight=weight,
                    active=active,
                )
            )
        return GoalsSummary(
            total=total,
            active=active_count,
            active_weight_total=round(active_weight_total, 3),
            items=summary_items,
        )

    def _build_budget_summary(self, context: dict[str, Any]) -> BudgetSummarySnapshot:
        budget = context.get("budget")
        if not isinstance(budget, dict):
            return BudgetSummarySnapshot()
        members = budget.get("members")
        member_items = members if isinstance(members, list) else []
        snapshots: list[BudgetMemberSnapshot] = []
        for member in member_items:
            if not isinstance(member, dict):
                continue
            member_id = member.get("member_id")
            if not isinstance(member_id, int):
                continue
            if len(snapshots) >= MAX_SUMMARY_ITEMS_PER_DOMAIN:
                continue
            snapshots.append(
                BudgetMemberSnapshot(
                    member_id=member_id,
                    display_name=str(member.get("display_name") or f"Member #{member_id}"),
                    allowance=int(member.get("allowance") or 0),
                    used=int(member.get("used") or 0),
                    remaining=int(member.get("remaining") or 0),
                )
            )
        return BudgetSummarySnapshot(
            threshold_1_to_5=float(budget["threshold_1_to_5"]) if isinstance(budget.get("threshold_1_to_5"), (int, float)) else None,
            period_start_date=budget.get("period_start_date"),
            period_end_date=budget.get("period_end_date"),
            default_allowance=int(budget["default_allowance"]) if isinstance(budget.get("default_allowance"), int) else None,
            members=snapshots,
        )

    def _summary_counts(self, summary: AgentSummary | None) -> dict[str, int]:
        if summary is None:
            return {}
        counts: dict[str, int] = {}
        if summary.roadmap is not None:
            counts["roadmap_total"] = summary.roadmap.total
        if summary.decisions is not None:
            counts["decisions_total"] = summary.decisions.total
        if summary.goals is not None:
            counts["goals_total"] = summary.goals.total
        if summary.budget is not None:
            counts["budget_members"] = len(summary.budget.members)
        return counts

    def _save_session(self, tools: Any, family_id: int, session_id: str, actor: str, state: dict[str, Any]) -> None:
        try:
            tools.put_agent_session(family_id, self.name, session_id, state=state, status="active", actor_email=actor)
        except Exception:
            return

    def _fallback_draft(self, message: str) -> DecisionDraft:
        title = message.strip().split("\n", 1)[0][:120] or "Decision request"
        return DecisionDraft(
            title=title,
            description=message.strip() or title,
            options=[],
            target_date=None,
            participants=[],
            constraints=[],
            budget=None,
            decision_type="other",
            assumptions=[],
        )

    def _response(
        self,
        *,
        session_id: str,
        status: str,
        intent: str,
        plan: DecisionActionPlan | None,
        execution: DecisionExecution,
        pending: PendingConfirmation,
        explanation: str,
        artifacts: dict[str, list[int]],
        raw_tool_trace: list[dict[str, Any]],
        draft: DecisionDraft,
        followups: list[str],
        summary: AgentSummary | None = None,
    ) -> DecisionAgentResponse:
        legacy_followups = followups if followups else ([] if status != "pending_confirmation" else [pending.prompt or "confirm or cancel"])
        return DecisionAgentResponse(
            schema_version="2.0",
            status=status,  # type: ignore[arg-type]
            intent=intent,
            plan=plan,
            execution=execution,
            pending_confirmation=pending,
            explanation=explanation,
            summary=summary,
            artifacts=artifacts,
            raw_tool_trace=raw_tool_trace,
            session_id=session_id,
            draft=draft,
            cost_estimate=None,
            scoring=None,
            created_decision=None,
            updated_decision=None,
            created_roadmap_items=[],
            deconflicts=[],
            alignment_suggestions=[],
            legacy_explanation=DecisionExplanation(
                decision_definition=draft.title,
                key_facts_and_assumptions=[f"intent={intent}"],
                followups_asked=legacy_followups,
                scoring_notes=explanation,
            ),
        )

    def _audit(self, publisher: EventPublisher, family_id: int, actor: str, cid: str, *, event: str, extra: dict[str, Any]) -> None:
        try:
            publisher.publish_sync(
                Subjects.agent_audit(self.name),
                {"event": event, **extra},
                actor=actor,
                family_id=family_id,
                source="agents.decision_agent",
                correlation_id=cid,
            )
        except Exception:
            return


def _collect_artifacts(artifacts: dict[str, list[int]], result: dict[str, Any] | None) -> None:
    if not isinstance(result, dict):
        return
    for key in ("id", "family_id", "member_id", "goal_id", "decision_id", "roadmap_id"):
        value = result.get(key)
        if isinstance(value, int):
            artifacts.setdefault(key, [])
            if value not in artifacts[key]:
                artifacts[key].append(value)


def _parse_confirmation_intent(msg: str) -> str:
    s = (msg or "").strip().lower()
    if not s:
        return "ambiguous"
    positive_patterns = [
        r"\bconfirm\b",
        r"\byes\b",
        r"\bproceed\b",
        r"\bdo it\b",
        r"\bgo ahead\b",
    ]
    negative_patterns = [
        r"\bcancel\b",
        r"\bstop\b",
        r"\bdon't\b",
        r"\bdo not\b",
        r"\babort\b",
    ]
    if any(re.search(pattern, s) for pattern in negative_patterns):
        return "cancel"
    if any(re.search(pattern, s) for pattern in positive_patterns):
        return "confirm"
    return "ambiguous"


def _merge_drafts(base: DecisionDraft, delta: DecisionDraft) -> DecisionDraft:
    """
    Retained for compatibility with existing tests and downstream imports.
    """

    def good_text(v: str | None, *, min_len: int) -> bool:
        if not v:
            return False
        s = v.strip()
        if len(s) < min_len:
            return False
        if all(ch.isdigit() or ch in " .,$" for ch in s):
            return False
        return True

    title = base.title
    if good_text(delta.title, min_len=8):
        title = delta.title.strip()

    description = base.description
    if good_text(delta.description, min_len=20):
        ds = delta.description.strip()
        if ds not in description:
            description = (description.rstrip() + "\n\n" + ds).strip()

    merged = base.model_copy(update={"title": title, "description": description})
    if delta.target_date is not None:
        merged.target_date = delta.target_date
    if delta.budget is not None:
        merged.budget = delta.budget
    if delta.decision_type and delta.decision_type != "other":
        merged.decision_type = delta.decision_type

    def merge_list(a: list[str], b: list[str]) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for item in (a or []) + (b or []):
            s = (item or "").strip()
            if not s:
                continue
            k = s.lower()
            if k in seen:
                continue
            seen.add(k)
            out.append(s)
        return out

    merged.options = merge_list(base.options, delta.options)
    merged.participants = merge_list(base.participants, delta.participants)
    merged.constraints = merge_list(base.constraints, delta.constraints)
    merged.assumptions = merge_list(base.assumptions, delta.assumptions)
    return merged
