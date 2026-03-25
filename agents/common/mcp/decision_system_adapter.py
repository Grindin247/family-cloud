from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from uuid import uuid4
from typing import Any, Literal

from agents.common.decision_types import OperationType, PlannedOperation
from agents.common.mcp.client import HttpToolClient
from agents.common.settings import settings


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
            "scope_type": payload.get("scope_type", "family"),
            "owner_person_id": payload.get("owner_person_id"),
            "visibility_scope": payload.get("visibility_scope"),
            "name": payload["name"],
            "description": payload["description"],
            "weight": payload["weight"],
            "action_types": payload.get("action_types", []),
            "status": payload.get("status", "active"),
            "priority": payload.get("priority"),
            "horizon": payload.get("horizon"),
            "target_date": payload.get("target_date"),
            "success_criteria": payload.get("success_criteria"),
            "review_cadence_days": payload.get("review_cadence_days"),
            "next_review_at": payload.get("next_review_at"),
            "tags": payload.get("tags", []),
            "external_refs": payload.get("external_refs", []),
        }
        return _OperationPlan(op_type, payload, "POST", "/goals", body, False, f"Create goal '{payload['name']}'")
    if op_type == "update_goal":
        _required(payload, ["goal_id"], op_type)
        patch = {
            key: payload[key]
            for key in [
                "scope_type",
                "owner_person_id",
                "visibility_scope",
                "name",
                "description",
                "weight",
                "action_types",
                "status",
                "priority",
                "horizon",
                "target_date",
                "success_criteria",
                "review_cadence_days",
                "next_review_at",
                "tags",
                "external_refs",
            ]
            if key in payload
        }
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
            "person_allowances": payload.get("person_allowances", []),
        }
        return _OperationPlan(op_type, payload, "PUT", f"/budgets/families/{family_id}/policy", body, False, f"Update budget policy for family #{family_id}")
    if op_type == "reset_budget_period":
        _required(payload, ["family_id"], op_type)
        return _OperationPlan(op_type, payload, "POST", f"/budgets/families/{payload['family_id']}/period/reset", None, False, f"Reset budget period for family #{payload['family_id']}")

    raise ValueError(f"unsupported operation type: {op_type}")


@dataclass
class DecisionSystemTools:
    http: HttpToolClient
    file_http: HttpToolClient | None = None
    event_http: HttpToolClient | None = None
    question_http: HttpToolClient | None = None

    def _headers(self, actor_email: str | None) -> dict[str, str] | None:
        return {"X-Dev-User": actor_email} if actor_email else None

    def _file_client(self) -> HttpToolClient:
        return self.file_http or HttpToolClient(base_url=settings.file_api_base_url)

    def _event_client(self) -> HttpToolClient:
        return self.event_http or HttpToolClient(base_url=settings.family_event_api_base_url)

    def _question_client(self) -> HttpToolClient:
        return self.question_http or HttpToolClient(base_url=settings.question_api_base_url)

    def list_families(self, *, actor_email: str | None = None) -> list[dict[str, Any]]:
        return self.http.request("GET", "/families", headers=self._headers(actor_email)).result["items"]

    def list_family_members(self, family_id: int, *, actor_email: str | None = None) -> list[dict[str, Any]]:
        return self.http.request("GET", f"/families/{family_id}/members", headers=self._headers(actor_email)).result["items"]

    def list_family_persons(self, family_id: int, *, actor_email: str | None = None) -> list[dict[str, Any]]:
        return self.http.request("GET", f"/families/{family_id}/persons", headers=self._headers(actor_email)).result["items"]

    def get_resolved_context(
        self,
        family_id: int,
        *,
        actor_email: str,
        target_person_id: str | None = None,
        source_channel: str | None = None,
        source_sender_id: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if target_person_id is not None:
            params["target_person_id"] = target_person_id
        if source_channel is not None:
            params["source_channel"] = source_channel
        if source_sender_id is not None:
            params["source_sender_id"] = source_sender_id
        return self.http.request(
            "GET",
            f"/families/{family_id}/context",
            params=params,
            headers=self._headers(actor_email),
        ).result

    def resolve_person_alias(self, family_id: int, query: str, *, actor_email: str | None = None) -> dict[str, Any]:
        return self.http.request(
            "GET",
            f"/families/{family_id}/resolve-alias",
            params={"q": query},
            headers=self._headers(actor_email),
        ).result

    def resolve_sender(
        self,
        family_id: int,
        *,
        source_channel: str,
        source_sender_id: str,
        actor_email: str | None = None,
    ) -> dict[str, Any]:
        return self.http.request(
            "POST",
            "/identity/resolve-sender",
            json_body={
                "family_id": family_id,
                "source_channel": source_channel,
                "source_sender_id": source_sender_id,
            },
            headers=self._headers(actor_email),
        ).result

    def list_family_features(self, family_id: int, *, actor_email: str | None = None) -> list[dict[str, Any]]:
        return self.http.request("GET", f"/families/{family_id}/features", headers=self._headers(actor_email)).result["items"]

    def get_family_goals(
        self,
        family_id: int,
        *,
        scope_type: str | None = None,
        owner_person_id: str | None = None,
        status: str | None = None,
        include_deleted: bool = False,
        actor_email: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"family_id": family_id, "include_deleted": include_deleted}
        if scope_type is not None:
            params["scope_type"] = scope_type
        if owner_person_id is not None:
            params["owner_person_id"] = owner_person_id
        if status is not None:
            params["status"] = status
        return self.http.request("GET", "/goals", params=params, headers=self._headers(actor_email)).result["items"]

    def list_decisions(
        self,
        family_id: int,
        *,
        scope_type: str | None = None,
        owner_person_id: str | None = None,
        target_person_id: str | None = None,
        goal_policy: str | None = None,
        include_deleted: bool = False,
        include_scores: bool = False,
        actor_email: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "family_id": family_id,
            "include_scores": include_scores,
            "include_deleted": include_deleted,
        }
        if scope_type is not None:
            params["scope_type"] = scope_type
        if owner_person_id is not None:
            params["owner_person_id"] = owner_person_id
        if target_person_id is not None:
            params["target_person_id"] = target_person_id
        if goal_policy is not None:
            params["goal_policy"] = goal_policy
        return self.http.request(
            "GET",
            "/decisions",
            params=params,
            headers=self._headers(actor_email),
        ).result["items"]

    def list_roadmap_items(self, family_id: int, *, actor_email: str | None = None) -> list[dict[str, Any]]:
        return self.http.request("GET", "/roadmap", params={"family_id": family_id}, headers=self._headers(actor_email)).result["items"]

    def get_budget_summary(self, family_id: int, *, actor_email: str | None = None) -> dict[str, Any]:
        return self.http.request("GET", f"/budgets/families/{family_id}", headers=self._headers(actor_email)).result

    def get_decision(self, decision_id: int, *, actor_email: str | None = None) -> dict[str, Any]:
        return self.http.request("GET", f"/decisions/{decision_id}", headers=self._headers(actor_email)).result

    def get_decision_goal_context(self, decision_id: int, *, actor_email: str | None = None) -> dict[str, Any]:
        return self.http.request("GET", f"/decisions/{decision_id}/goal-context", headers=self._headers(actor_email)).result

    def get_decision_score_runs(self, decision_id: int, *, actor_email: str | None = None) -> list[dict[str, Any]]:
        return self.http.request("GET", f"/decisions/{decision_id}/score-runs", headers=self._headers(actor_email)).result["items"]

    def get_goal(self, goal_id: int, *, actor_email: str | None = None) -> dict[str, Any]:
        return self.http.request("GET", f"/goals/{goal_id}", headers=self._headers(actor_email)).result

    def get_family_dna(self, family_id: int, *, actor_email: str | None = None) -> dict[str, Any]:
        return self.http.request("GET", f"/family/{family_id}/dna", headers=self._headers(actor_email)).result

    def write_memory(
        self,
        family_id: int,
        type: str,
        text: str,
        *,
        actor_email: str | None = None,
        owner_person_id: str | None = None,
        visibility_scope: str = "family",
        source_refs: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return self.http.request(
            "POST",
            f"/family/{family_id}/memory/documents",
            json_body={
                "family_id": family_id,
                "type": type,
                "text": text,
                "source_refs": source_refs or [],
                "owner_person_id": owner_person_id,
                "visibility_scope": visibility_scope,
            },
            headers=self._headers(actor_email),
        ).result

    def search_memory(self, family_id: int, query: str, *, top_k: int = 5, actor_email: str | None = None) -> dict[str, Any]:
        return self.http.request(
            "POST",
            f"/family/{family_id}/memory/search",
            json_body={"query": query, "top_k": top_k},
            headers=self._headers(actor_email),
        ).result

    def search_notes(
        self,
        family_id: int,
        query: str,
        *,
        top_k: int = 5,
        include_content: bool = True,
        actor_email: str | None = None,
        owner_person_id: str | None = None,
    ) -> dict[str, Any]:
        return self._file_client().request(
            "POST",
            "/notes/search",
            json_body={
                "family_id": family_id,
                "actor": actor_email or "system",
                "query": query,
                "top_k": top_k,
                "include_content": include_content,
                "owner_person_id": owner_person_id,
            },
            headers=self._headers(actor_email),
        ).result

    def index_file_document(
        self,
        family_id: int,
        path: str,
        item_type: str,
        role: str,
        *,
        actor_email: str | None = None,
        source_session_id: str | None = None,
        name: str | None = None,
        title: str | None = None,
        summary: str | None = None,
        body_text: str | None = None,
        excerpt_text: str | None = None,
        content_type: str | None = None,
        media_kind: str | None = None,
        source_date: str | None = None,
        size_bytes: int | None = None,
        etag: str | None = None,
        file_id: str | None = None,
        is_directory: bool = False,
        tags: list[str] | None = None,
        nextcloud_url: str | None = None,
        related_paths: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        owner_person_id: str | None = None,
    ) -> dict[str, Any]:
        return self._file_client().request(
            "POST",
            "/files/index",
            json_body={
                "family_id": family_id,
                "actor": actor_email or "system",
                "source_session_id": source_session_id,
                "path": path,
                "name": name,
                "item_type": item_type,
                "role": role,
                "title": title,
                "summary": summary,
                "body_text": body_text,
                "excerpt_text": excerpt_text,
                "content_type": content_type,
                "media_kind": media_kind,
                "source_date": source_date,
                "size_bytes": size_bytes,
                "etag": etag,
                "file_id": file_id,
                "is_directory": is_directory,
                "tags": tags or [],
                "nextcloud_url": nextcloud_url,
                "related_paths": related_paths or [],
                "metadata": metadata or {},
                "owner_person_id": owner_person_id,
            },
            headers=self._headers(actor_email),
        ).result

    def search_files(
        self,
        family_id: int,
        query: str,
        *,
        top_k: int = 5,
        include_content: bool = True,
        preferred_item_types: list[str] | None = None,
        content_types: list[str] | None = None,
        actor_email: str | None = None,
        owner_person_id: str | None = None,
    ) -> dict[str, Any]:
        return self._file_client().request(
            "POST",
            "/files/search",
            json_body={
                "family_id": family_id,
                "actor": actor_email or "system",
                "query": query,
                "top_k": top_k,
                "include_content": include_content,
                "preferred_item_types": preferred_item_types or [],
                "content_types": content_types or [],
                "owner_person_id": owner_person_id,
            },
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

    def create_agent_question(
        self,
        family_id: int,
        *,
        domain: str,
        source_agent: str,
        topic: str,
        summary: str,
        prompt: str,
        urgency: str,
        topic_type: str,
        dedupe_key: str,
        context: dict[str, Any] | None = None,
        artifact_refs: list[dict[str, Any]] | None = None,
        due_at: str | None = None,
        expires_at: str | None = None,
        actor_email: str | None = None,
    ) -> dict[str, Any]:
        return self._question_client().request(
            "POST",
            f"/families/{family_id}/questions",
            json_body={
                "domain": domain,
                "source_agent": source_agent,
                "topic": topic,
                "summary": summary,
                "prompt": prompt,
                "urgency": urgency,
                "category": topic_type,
                "topic_type": topic_type,
                "dedupe_key": dedupe_key,
                "context": context or {},
                "artifact_refs": artifact_refs or [],
                "due_at": due_at,
                "expires_at": expires_at,
            },
            headers=self._headers(actor_email),
        ).result

    def list_agent_questions(
        self,
        family_id: int,
        *,
        domain: str | None = None,
        status: str | None = None,
        include_inactive: bool = False,
        actor_email: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"include_inactive": include_inactive}
        if domain is not None:
            params["domain"] = domain
        if status is not None:
            params["status"] = status
        return self._question_client().request(
            "GET",
            f"/families/{family_id}/questions",
            params=params,
            headers=self._headers(actor_email),
        ).result["items"]

    def update_agent_question(
        self,
        family_id: int,
        question_id: str,
        *,
        status: str | None = None,
        summary: str | None = None,
        prompt: str | None = None,
        answer_sufficiency_state: str | None = None,
        context_patch: dict[str, Any] | None = None,
        actor_email: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"context_patch": context_patch or {}}
        if status is not None:
            body["status"] = status
        if summary is not None:
            body["summary"] = summary
        if prompt is not None:
            body["prompt"] = prompt
        if answer_sufficiency_state is not None:
            body["answer_sufficiency_state"] = answer_sufficiency_state
        return self._question_client().request(
            "PATCH",
            f"/families/{family_id}/questions/{question_id}",
            json_body=body,
            headers=self._headers(actor_email),
        ).result

    def mark_agent_question_asked(
        self,
        family_id: int,
        question_id: str,
        *,
        delivery_agent: str,
        delivery_channel: str = "discord_dm",
        claim_token: str | None = None,
        actor_email: str | None = None,
    ) -> dict[str, Any]:
        return self._question_client().request(
            "POST",
            f"/families/{family_id}/questions/{question_id}/asked",
            json_body={"delivery_agent": delivery_agent, "delivery_channel": delivery_channel, "claim_token": claim_token, "delivery_context": {}},
            headers=self._headers(actor_email),
        ).result

    def answer_agent_question(
        self,
        family_id: int,
        question_id: str,
        *,
        answer_text: str,
        status: str = "resolved",
        actor_email: str | None = None,
    ) -> dict[str, Any]:
        return self._question_client().request(
            "POST",
            f"/families/{family_id}/questions/{question_id}/answer",
            json_body={"answer_text": answer_text, "status": status},
            headers=self._headers(actor_email),
        ).result

    def claim_agent_questions(
        self,
        family_id: int,
        *,
        agent_id: str,
        channel: str = "discord_dm",
        force: bool = False,
        actor_email: str | None = None,
    ) -> dict[str, Any]:
        return self._question_client().request(
            "POST",
            f"/families/{family_id}/questions/claim-next",
            json_body={"agent_id": agent_id, "channel": channel, "force": force},
            headers=self._headers(actor_email),
        ).result

    def resolve_agent_question(
        self,
        family_id: int,
        question_id: str,
        *,
        status: str = "resolved",
        resolution_note: str | None = None,
        answer_sufficiency_state: str | None = None,
        context_patch: dict[str, Any] | None = None,
        actor_email: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"status": status, "context_patch": context_patch or {}}
        if resolution_note is not None:
            body["resolution_note"] = resolution_note
        if answer_sufficiency_state is not None:
            body["answer_sufficiency_state"] = answer_sufficiency_state
        return self._question_client().request(
            "POST",
            f"/families/{family_id}/questions/{question_id}/resolve",
            json_body=body,
            headers=self._headers(actor_email),
        ).result

    def record_agent_event(
        self,
        family_id: int,
        *,
        domain: str,
        source_agent: str,
        event_type: str,
        summary: str,
        topic: str | None = None,
        status: str | None = None,
        value_number: float | None = None,
        payload: dict[str, Any] | None = None,
        actor_email: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "domain": domain,
            "source_agent": source_agent,
            "event_type": event_type,
            "summary": summary,
            "payload": payload or {},
        }
        if topic is not None:
            body["topic"] = topic
        if status is not None:
            body["status"] = status
        if value_number is not None:
            body["value_number"] = value_number
        return self.http.request(
            "POST",
            f"/family/{family_id}/ops/events",
            json_body=body,
            headers=self._headers(actor_email),
        ).result

    def record_family_event(self, event: dict[str, Any], *, actor_email: str | None = None) -> dict[str, Any]:
        return self._event_client().request(
            "POST",
            "/events",
            json_body=event,
            headers=self._headers(actor_email),
        ).result

    def list_family_events(
        self,
        family_id: int,
        *,
        domain: str | None = None,
        domains: list[str] | None = None,
        event_type: str | None = None,
        tag: str | None = None,
        subject_id: str | None = None,
        actor_filter: str | None = None,
        start: str | None = None,
        end: str | None = None,
        limit: int = 100,
        offset: int = 0,
        actor_email: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"family_id": family_id, "limit": limit, "offset": offset}
        if domain is not None:
            params["domain"] = domain
        if domains:
            params["domains"] = domains
        if event_type is not None:
            params["event_type"] = event_type
        if tag is not None:
            params["tag"] = tag
        if subject_id is not None:
            params["subject_id"] = subject_id
        if actor_filter is not None:
            params["actor_id"] = actor_filter
        if start is not None:
            params["start"] = start
        if end is not None:
            params["end"] = end
        return self._event_client().request("GET", "/events", params=params, headers=self._headers(actor_email)).result

    def get_family_timeline(
        self,
        family_id: int,
        *,
        domain: str | None = None,
        domains: list[str] | None = None,
        event_type: str | None = None,
        tag: str | None = None,
        start: str | None = None,
        end: str | None = None,
        limit: int = 100,
        actor_email: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"family_id": family_id, "limit": limit}
        if domain is not None:
            params["domain"] = domain
        if domains:
            params["domains"] = domains
        if event_type is not None:
            params["event_type"] = event_type
        if tag is not None:
            params["tag"] = tag
        if start is not None:
            params["start"] = start
        if end is not None:
            params["end"] = end
        return self._event_client().request("GET", "/timeline", params=params, headers=self._headers(actor_email)).result

    def get_family_event_counts(
        self,
        family_id: int,
        *,
        domain: str | None = None,
        domains: list[str] | None = None,
        event_type: str | None = None,
        tag: str | None = None,
        start: str | None = None,
        end: str | None = None,
        actor_email: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"family_id": family_id}
        if domain is not None:
            params["domain"] = domain
        if domains:
            params["domains"] = domains
        if event_type is not None:
            params["event_type"] = event_type
        if tag is not None:
            params["tag"] = tag
        if start is not None:
            params["start"] = start
        if end is not None:
            params["end"] = end
        return self._event_client().request("GET", "/analytics/counts", params=params, headers=self._headers(actor_email)).result

    def get_family_event_time_series(
        self,
        family_id: int,
        *,
        metric: str,
        bucket: str,
        domain: str | None = None,
        domains: list[str] | None = None,
        event_type: str | None = None,
        tag: str | None = None,
        start: str | None = None,
        end: str | None = None,
        actor_email: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"family_id": family_id, "metric": metric, "bucket": bucket}
        if domain is not None:
            params["domain"] = domain
        if domains:
            params["domains"] = domains
        if event_type is not None:
            params["event_type"] = event_type
        if tag is not None:
            params["tag"] = tag
        if start is not None:
            params["start"] = start
        if end is not None:
            params["end"] = end
        return self._event_client().request("GET", "/analytics/time-series", params=params, headers=self._headers(actor_email)).result

    def get_family_event_domain_summary(
        self,
        family_id: int,
        *,
        start: str | None = None,
        end: str | None = None,
        actor_email: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"family_id": family_id}
        if start is not None:
            params["start"] = start
        if end is not None:
            params["end"] = end
        return self._event_client().request("GET", "/analytics/domain-summary", params=params, headers=self._headers(actor_email)).result

    def query_agent_metrics(
        self,
        family_id: int,
        *,
        domain: str | None = None,
        metric_keys: list[str] | None = None,
        start_at: str | None = None,
        end_at: str | None = None,
        actor_email: str | None = None,
    ) -> list[dict[str, Any]]:
        body: dict[str, Any] = {"metric_keys": metric_keys or []}
        if domain is not None:
            body["domain"] = domain
        if start_at is not None:
            body["start_at"] = start_at
        if end_at is not None:
            body["end_at"] = end_at
        return self.http.request(
            "POST",
            f"/family/{family_id}/ops/metrics/query",
            json_body=body,
            headers=self._headers(actor_email),
        ).result["items"]

    def get_playback_timeline(
        self,
        family_id: int,
        *,
        domain: str | None = None,
        event_types: list[str] | None = None,
        start_at: str | None = None,
        end_at: str | None = None,
        limit: int = 100,
        actor_email: str | None = None,
    ) -> list[dict[str, Any]]:
        body: dict[str, Any] = {"event_types": event_types or [], "limit": limit}
        if domain is not None:
            body["domain"] = domain
        if start_at is not None:
            body["start_at"] = start_at
        if end_at is not None:
            body["end_at"] = end_at
        return self.http.request(
            "POST",
            f"/family/{family_id}/ops/playback/query",
            json_body=body,
            headers=self._headers(actor_email),
        ).result["items"]

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
