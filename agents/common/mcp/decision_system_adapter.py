from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from uuid import uuid4
from typing import Any, Literal

from agents.common.mcp.client import HttpToolClient
from agents.common.settings import settings
from agents.decision_agent.schemas import OperationType, PlannedOperation


ProposalStatus = Literal["proposed", "confirmed", "committed", "canceled"]


@dataclass
class _OperationPlan:
    type: OperationType
    payload: dict[str, Any]
    method: str
    path: str
    body: dict[str, Any] | None
    destructive: bool
    summary: str


@dataclass
class _Proposal:
    id: str
    actor_id: str
    actor_name: str | None
    rationale: str
    status: ProposalStatus
    operations: list[PlannedOperation]
    operation_preview: list[str]
    allow_destructive: bool
    commit_results: list[dict[str, Any]] = field(default_factory=list)


_proposal_lock = Lock()
_proposals: dict[str, _Proposal] = {}


def _required(payload: dict[str, Any], fields: list[str], op_type: OperationType) -> None:
    missing = [field for field in fields if field not in payload]
    if missing:
        raise ValueError(f"{op_type} missing required field(s): {', '.join(missing)}")


def _to_plan(op: PlannedOperation) -> _OperationPlan:
    payload = op.payload
    op_type = op.type

    if op_type == "create_family":
        _required(payload, ["name"], op_type)
        return _OperationPlan(op_type, payload, "POST", "/families", {"name": payload["name"]}, False, f"Create family '{payload['name']}'")
    if op_type == "update_family":
        _required(payload, ["family_id", "name"], op_type)
        return _OperationPlan(op_type, payload, "PATCH", f"/families/{payload['family_id']}", {"name": payload["name"]}, False, f"Update family #{payload['family_id']}")
    if op_type == "delete_family":
        _required(payload, ["family_id"], op_type)
        return _OperationPlan(op_type, payload, "DELETE", f"/families/{payload['family_id']}", None, True, f"Delete family #{payload['family_id']}")
    if op_type == "create_member":
        _required(payload, ["family_id", "email", "display_name", "role"], op_type)
        family_id = int(payload["family_id"])
        body = {"email": payload["email"], "display_name": payload["display_name"], "role": payload["role"]}
        return _OperationPlan(op_type, payload, "POST", f"/families/{family_id}/members", body, False, f"Create member in family #{family_id}")
    if op_type == "update_member":
        _required(payload, ["family_id", "member_id"], op_type)
        patch = {key: payload[key] for key in ["display_name", "role"] if key in payload}
        if not patch:
            raise ValueError("update_member requires display_name and/or role")
        return _OperationPlan(op_type, payload, "PATCH", f"/families/{payload['family_id']}/members/{payload['member_id']}", patch, False, f"Update member #{payload['member_id']}")
    if op_type == "delete_member":
        _required(payload, ["family_id", "member_id"], op_type)
        return _OperationPlan(op_type, payload, "DELETE", f"/families/{payload['family_id']}/members/{payload['member_id']}", None, True, f"Delete member #{payload['member_id']}")
    if op_type == "create_goal":
        _required(payload, ["family_id", "name", "description", "weight"], op_type)
        body = {
            "family_id": payload["family_id"],
            "name": payload["name"],
            "description": payload["description"],
            "weight": payload["weight"],
            "action_types": payload.get("action_types", []),
            "active": payload.get("active", True),
        }
        return _OperationPlan(op_type, payload, "POST", "/goals", body, False, f"Create goal '{payload['name']}'")
    if op_type == "update_goal":
        _required(payload, ["goal_id"], op_type)
        patch = {key: payload[key] for key in ["name", "description", "weight", "action_types", "active"] if key in payload}
        if not patch:
            raise ValueError("update_goal requires at least one mutable field")
        return _OperationPlan(op_type, payload, "PATCH", f"/goals/{payload['goal_id']}", patch, False, f"Update goal #{payload['goal_id']}")
    if op_type == "delete_goal":
        _required(payload, ["goal_id"], op_type)
        return _OperationPlan(op_type, payload, "DELETE", f"/goals/{payload['goal_id']}", None, True, f"Delete goal #{payload['goal_id']}")
    if op_type == "create_decision":
        _required(payload, ["family_id", "title", "description"], op_type)
        return _OperationPlan(op_type, payload, "POST", "/decisions", payload, False, f"Create decision '{payload['title']}'")
    if op_type == "update_decision":
        _required(payload, ["decision_id"], op_type)
        patch = {k: v for k, v in payload.items() if k != "decision_id"}
        if not patch:
            raise ValueError("update_decision requires at least one mutable field")
        return _OperationPlan(op_type, payload, "PATCH", f"/decisions/{payload['decision_id']}", patch, False, f"Update decision #{payload['decision_id']}")
    if op_type == "delete_decision":
        _required(payload, ["decision_id"], op_type)
        return _OperationPlan(op_type, payload, "DELETE", f"/decisions/{payload['decision_id']}", None, True, f"Delete decision #{payload['decision_id']}")
    if op_type == "score_decision":
        normalized = dict(payload)
        if "goal_scores" not in normalized:
            for alias in ("scores", "goal_score", "score_inputs"):
                value = normalized.get(alias)
                if value is not None:
                    normalized["goal_scores"] = value
                    break
        if "threshold_1_to_5" not in normalized:
            for alias in ("threshold", "score_threshold_1_to_5"):
                value = normalized.get(alias)
                if value is not None:
                    normalized["threshold_1_to_5"] = value
                    break
        if "threshold_1_to_5" not in normalized:
            normalized["threshold_1_to_5"] = float(settings.decision_threshold_1_to_5)
        _required(normalized, ["decision_id", "goal_scores", "threshold_1_to_5"], op_type)
        body = {
            "goal_scores": normalized["goal_scores"],
            "threshold_1_to_5": normalized["threshold_1_to_5"],
            "computed_by": normalized.get("computed_by", "ai"),
        }
        return _OperationPlan(
            op_type,
            normalized,
            "POST",
            f"/decisions/{normalized['decision_id']}/score",
            body,
            False,
            f"Score decision #{normalized['decision_id']}",
        )
    if op_type == "create_roadmap_item":
        _required(payload, ["decision_id", "bucket", "status"], op_type)
        body = {
            "decision_id": payload["decision_id"],
            "bucket": payload["bucket"],
            "status": payload["status"],
            "start_date": payload.get("start_date"),
            "end_date": payload.get("end_date"),
            "dependencies": payload.get("dependencies", []),
            "use_discretionary_budget": payload.get("use_discretionary_budget", False),
        }
        return _OperationPlan(op_type, payload, "POST", "/roadmap", body, False, f"Create roadmap item for decision #{payload['decision_id']}")
    if op_type == "update_roadmap_item":
        _required(payload, ["roadmap_id"], op_type)
        patch = {k: v for k, v in payload.items() if k != "roadmap_id"}
        if not patch:
            raise ValueError("update_roadmap_item requires at least one mutable field")
        return _OperationPlan(op_type, payload, "PATCH", f"/roadmap/{payload['roadmap_id']}", patch, False, f"Update roadmap item #{payload['roadmap_id']}")
    if op_type == "delete_roadmap_item":
        _required(payload, ["roadmap_id"], op_type)
        return _OperationPlan(op_type, payload, "DELETE", f"/roadmap/{payload['roadmap_id']}", None, True, f"Delete roadmap item #{payload['roadmap_id']}")
    if op_type == "update_budget_policy":
        _required(payload, ["family_id", "threshold_1_to_5", "period_days", "default_allowance"], op_type)
        family_id = int(payload["family_id"])
        body = {
            "threshold_1_to_5": payload["threshold_1_to_5"],
            "period_days": payload["period_days"],
            "default_allowance": payload["default_allowance"],
            "member_allowances": payload.get("member_allowances", []),
        }
        return _OperationPlan(op_type, payload, "PUT", f"/budgets/families/{family_id}/policy", body, False, f"Update budget policy for family #{family_id}")
    if op_type == "reset_budget_period":
        _required(payload, ["family_id"], op_type)
        return _OperationPlan(op_type, payload, "POST", f"/budgets/families/{payload['family_id']}/period/reset", None, False, f"Reset budget period for family #{payload['family_id']}")

    raise ValueError(f"unsupported operation type: {op_type}")


@dataclass
class DecisionSystemTools:
    http: HttpToolClient

    def _headers(self, actor_email: str | None) -> dict[str, str] | None:
        return {"X-Dev-User": actor_email} if actor_email else None

    def list_families(self, *, actor_email: str | None = None) -> list[dict[str, Any]]:
        return self.http.request("GET", "/families", headers=self._headers(actor_email)).result["items"]

    def list_family_members(self, family_id: int, *, actor_email: str | None = None) -> list[dict[str, Any]]:
        return self.http.request("GET", f"/families/{family_id}/members", headers=self._headers(actor_email)).result["items"]

    def get_family_goals(self, family_id: int, *, actor_email: str | None = None) -> list[dict[str, Any]]:
        return self.http.request("GET", "/goals", params={"family_id": family_id}, headers=self._headers(actor_email)).result["items"]

    def list_decisions(self, family_id: int, *, include_scores: bool = False, actor_email: str | None = None) -> list[dict[str, Any]]:
        return self.http.request(
            "GET",
            "/decisions",
            params={"family_id": family_id, "include_scores": include_scores},
            headers=self._headers(actor_email),
        ).result["items"]

    def list_roadmap_items(self, family_id: int, *, actor_email: str | None = None) -> list[dict[str, Any]]:
        return self.http.request("GET", "/roadmap", params={"family_id": family_id}, headers=self._headers(actor_email)).result["items"]

    def get_budget_summary(self, family_id: int, *, actor_email: str | None = None) -> dict[str, Any]:
        return self.http.request("GET", f"/budgets/families/{family_id}", headers=self._headers(actor_email)).result

    def write_memory(self, family_id: int, type: str, text: str, *, actor_email: str | None = None) -> dict[str, Any]:
        return self.http.request(
            "POST",
            f"/family/{family_id}/memory/documents",
            json_body={"family_id": family_id, "type": type, "text": text, "source_refs": []},
            headers=self._headers(actor_email),
        ).result

    def get_agent_session(self, family_id: int, agent_name: str, session_id: str, *, actor_email: str | None = None) -> dict[str, Any] | None:
        try:
            return self.http.request(
                "GET",
                f"/family/{family_id}/agents/{agent_name}/sessions/{session_id}",
                headers=self._headers(actor_email),
            ).result
        except Exception:
            return None

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
        try:
            return self.http.request(
                "PUT",
                f"/family/{family_id}/agents/{agent_name}/sessions/{session_id}",
                json_body={"status": status, "state": state},
                headers=self._headers(actor_email),
            ).result
        except Exception:
            return None

    def delete_agent_session(self, family_id: int, agent_name: str, session_id: str, *, actor_email: str | None = None) -> None:
        try:
            self.http.request("DELETE", f"/family/{family_id}/agents/{agent_name}/sessions/{session_id}", headers=self._headers(actor_email))
        except Exception:
            return

    def propose_changes(
        self,
        *,
        actor_id: str,
        actor_name: str | None,
        rationale: str,
        operations: list[PlannedOperation],
        allow_destructive: bool = False,
    ) -> dict[str, Any]:
        plans = [_to_plan(op) for op in operations]
        if not allow_destructive and any(plan.destructive for plan in plans):
            raise ValueError("destructive operations require allow_destructive=true")
        proposal_id = str(uuid4())
        proposal = _Proposal(
            id=proposal_id,
            actor_id=actor_id,
            actor_name=actor_name,
            rationale=rationale,
            status="proposed",
            operations=operations,
            operation_preview=[plan.summary for plan in plans],
            allow_destructive=allow_destructive,
        )
        with _proposal_lock:
            _proposals[proposal_id] = proposal
        return {
            "id": proposal.id,
            "status": proposal.status,
            "operation_preview": proposal.operation_preview,
            "allow_destructive": proposal.allow_destructive,
        }

    def get_proposal(self, proposal_id: str) -> dict[str, Any] | None:
        with _proposal_lock:
            proposal = _proposals.get(proposal_id)
        if proposal is None:
            return None
        return {
            "id": proposal.id,
            "actor_id": proposal.actor_id,
            "actor_name": proposal.actor_name,
            "rationale": proposal.rationale,
            "status": proposal.status,
            "operation_preview": proposal.operation_preview,
            "allow_destructive": proposal.allow_destructive,
            "operations": [op.model_dump(mode="json") for op in proposal.operations],
            "commit_results": proposal.commit_results,
        }

    def confirm_proposal(self, proposal_id: str, *, actor_id: str) -> dict[str, Any]:
        with _proposal_lock:
            proposal = _proposals.get(proposal_id)
            if proposal is None:
                raise ValueError("proposal not found")
            if proposal.actor_id != actor_id:
                raise ValueError("proposal actor mismatch")
            proposal.status = "confirmed"
        return {"id": proposal_id, "status": "confirmed"}

    def cancel_proposal(self, proposal_id: str, *, actor_id: str) -> dict[str, Any]:
        with _proposal_lock:
            proposal = _proposals.get(proposal_id)
            if proposal is None:
                raise ValueError("proposal not found")
            if proposal.actor_id != actor_id:
                raise ValueError("proposal actor mismatch")
            proposal.status = "canceled"
        return {"id": proposal_id, "status": "canceled"}

    def commit_proposal(self, proposal_id: str, *, actor_email: str | None = None) -> dict[str, Any]:
        with _proposal_lock:
            proposal = _proposals.get(proposal_id)
            if proposal is None:
                raise ValueError("proposal not found")
            if proposal.status != "confirmed":
                raise ValueError("proposal must be confirmed before commit")
            operations = list(proposal.operations)

        commit_results: list[dict[str, Any]] = []
        for operation in operations:
            plan = _to_plan(operation)
            try:
                result = self.http.request(
                    plan.method,
                    plan.path,
                    json_body=plan.body,
                    headers=self._headers(actor_email),
                ).result
                commit_results.append(
                    {
                        "type": operation.type,
                        "payload": operation.payload,
                        "ok": True,
                        "result": result,
                        "error": None,
                    }
                )
            except Exception as exc:
                commit_results.append(
                    {
                        "type": operation.type,
                        "payload": operation.payload,
                        "ok": False,
                        "result": None,
                        "error": str(exc),
                    }
                )

        with _proposal_lock:
            existing = _proposals.get(proposal_id)
            if existing is not None:
                existing.status = "committed"
                existing.commit_results = commit_results
        return {"id": proposal_id, "status": "committed", "commit_results": commit_results}
