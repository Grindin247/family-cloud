import json
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

import requests
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

SERVER_NAME = "decision-system-mcp"
API_BASE = os.getenv("DECISION_API_BASE_URL", "http://localhost:8000/v1").rstrip("/")
FILE_API_BASE = os.getenv("FILE_API_BASE_URL", API_BASE).rstrip("/")
EVENT_API_BASE = os.getenv("FAMILY_EVENT_API_BASE_URL", "http://localhost:8010/v1").rstrip("/")
QUESTION_API_BASE = os.getenv("QUESTION_API_BASE_URL", "http://localhost:8030/v1").rstrip("/")
REQUEST_TIMEOUT_SECONDS = float(os.getenv("DECISION_MCP_HTTP_TIMEOUT_SECONDS", "20"))
AUDIT_LOG_PATH = os.getenv("DECISION_MCP_AUDIT_LOG_PATH", ".decision_mcp_audit.jsonl")

OperationType = Literal[
    "create_family",
    "update_family",
    "delete_family",
    "create_member",
    "update_member",
    "delete_member",
    "create_goal",
    "update_goal",
    "delete_goal",
    "create_decision",
    "update_decision",
    "delete_decision",
    "score_decision",
    "create_roadmap_item",
    "update_roadmap_item",
    "delete_roadmap_item",
    "update_budget_policy",
    "reset_budget_period",
]


class Operation(BaseModel):
    type: OperationType
    payload: dict[str, Any] = Field(default_factory=dict)


class Proposal(BaseModel):
    id: str
    actor_id: str
    actor_name: str | None = None
    rationale: str
    status: Literal["proposed", "confirmed", "committed", "canceled"] = "proposed"
    operations: list[Operation]
    operation_preview: list[str]
    allow_destructive: bool = False
    created_at: str
    confirmed_at: str | None = None
    committed_at: str | None = None
    commit_results: list[dict[str, Any]] = Field(default_factory=list)


class _OperationPlan(BaseModel):
    summary: str
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    path: str
    body: dict[str, Any] | None = None
    destructive: bool = False


mcp = FastMCP(SERVER_NAME)
_proposal_lock = threading.Lock()
_proposals: dict[str, Proposal] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_audit_event(event_type: str, payload: dict[str, Any]) -> None:
    row = {"ts": _now_iso(), "event_type": event_type, **payload}
    with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, separators=(",", ":")) + "\n")


def _request(
    method: str,
    path: str,
    actor_id: str,
    actor_name: str | None,
    body: dict[str, Any] | None = None,
    query: dict[str, Any] | None = None,
) -> dict[str, Any]:
    headers = {
        "Content-Type": "application/json",
        "X-Decision-Actor-Id": actor_id,
    }
    if actor_id:
        headers["X-Dev-User"] = actor_id
    if actor_name:
        headers["X-Decision-Actor-Name"] = actor_name

    response = requests.request(
        method=method,
        url=f"{API_BASE}{path}",
        params=query,
        json=body,
        headers=headers,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if response.status_code == 204:
        return {"status_code": response.status_code, "body": None}

    try:
        parsed = response.json()
    except requests.JSONDecodeError:
        parsed = {"raw": response.text}

    if not response.ok:
        raise RuntimeError(f"{method} {path} failed ({response.status_code}): {parsed}")
    return {"status_code": response.status_code, "body": parsed}


def _event_request(
    method: str,
    path: str,
    actor_id: str,
    actor_name: str | None,
    body: dict[str, Any] | None = None,
    query: dict[str, Any] | None = None,
) -> dict[str, Any]:
    headers = {
        "Content-Type": "application/json",
        "X-Decision-Actor-Id": actor_id,
    }
    if actor_id:
        headers["X-Dev-User"] = actor_id
    if actor_name:
        headers["X-Decision-Actor-Name"] = actor_name
    response = requests.request(
        method=method,
        url=f"{EVENT_API_BASE}{path}",
        params=query,
        json=body,
        headers=headers,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if response.status_code == 204:
        return {"status_code": response.status_code, "body": None}
    try:
        parsed = response.json()
    except requests.JSONDecodeError:
        parsed = {"raw": response.text}
    if not response.ok:
        raise RuntimeError(f"{method} {path} failed ({response.status_code}): {parsed}")
    return {"status_code": response.status_code, "body": parsed}


def _file_request(
    method: str,
    path: str,
    actor_id: str,
    actor_name: str | None,
    body: dict[str, Any] | None = None,
    query: dict[str, Any] | None = None,
) -> dict[str, Any]:
    headers = {
        "Content-Type": "application/json",
        "X-Decision-Actor-Id": actor_id,
    }
    if actor_id:
        headers["X-Dev-User"] = actor_id
    if actor_name:
        headers["X-Decision-Actor-Name"] = actor_name

    response = requests.request(
        method=method,
        url=f"{FILE_API_BASE}{path}",
        params=query,
        json=body,
        headers=headers,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if response.status_code == 204:
        return {"status_code": response.status_code, "body": None}

    try:
        parsed = response.json()
    except requests.JSONDecodeError:
        parsed = {"raw": response.text}

    if not response.ok:
        raise RuntimeError(f"{method} {path} failed ({response.status_code}): {parsed}")
    return {"status_code": response.status_code, "body": parsed}


def _question_request(
    method: str,
    path: str,
    actor_id: str,
    actor_name: str | None,
    body: dict[str, Any] | None = None,
    query: dict[str, Any] | None = None,
) -> dict[str, Any]:
    headers = {
        "Content-Type": "application/json",
        "X-Decision-Actor-Id": actor_id,
    }
    if actor_id:
        headers["X-Dev-User"] = actor_id
    if actor_name:
        headers["X-Decision-Actor-Name"] = actor_name
    response = requests.request(
        method=method,
        url=f"{QUESTION_API_BASE}{path}",
        params=query,
        json=body,
        headers=headers,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if response.status_code == 204:
        return {"status_code": response.status_code, "body": None}
    try:
        parsed = response.json()
    except requests.JSONDecodeError:
        parsed = {"raw": response.text}
    if not response.ok:
        raise RuntimeError(f"{method} {path} failed ({response.status_code}): {parsed}")
    return {"status_code": response.status_code, "body": parsed}


def _required(payload: dict[str, Any], fields: list[str], op_type: str) -> None:
    missing = [field for field in fields if field not in payload]
    if missing:
        raise ValueError(f"{op_type} missing required field(s): {', '.join(missing)}")


def _to_plan(op: Operation) -> _OperationPlan:
    payload = op.payload
    op_type = op.type

    if op_type == "create_family":
        _required(payload, ["name"], op_type)
        return _OperationPlan(summary=f"Create family '{payload['name']}'", method="POST", path="/families", body={"name": payload["name"]})
    if op_type == "update_family":
        _required(payload, ["family_id", "name"], op_type)
        return _OperationPlan(
            summary=f"Update family #{payload['family_id']} name to '{payload['name']}'",
            method="PATCH",
            path=f"/families/{payload['family_id']}",
            body={"name": payload["name"]},
        )
    if op_type == "delete_family":
        _required(payload, ["family_id"], op_type)
        return _OperationPlan(
            summary=f"Delete family #{payload['family_id']}",
            method="DELETE",
            path=f"/families/{payload['family_id']}",
            destructive=True,
        )
    if op_type == "create_member":
        _required(payload, ["family_id", "email", "display_name", "role"], op_type)
        family_id = payload["family_id"]
        return _OperationPlan(
            summary=f"Create member '{payload['display_name']}' in family #{family_id}",
            method="POST",
            path=f"/families/{family_id}/members",
            body={
                "email": payload["email"],
                "display_name": payload["display_name"],
                "role": payload["role"],
            },
        )
    if op_type == "update_member":
        _required(payload, ["family_id", "member_id"], op_type)
        family_id = payload["family_id"]
        member_id = payload["member_id"]
        patch: dict[str, Any] = {}
        if "display_name" in payload:
            patch["display_name"] = payload["display_name"]
        if "role" in payload:
            patch["role"] = payload["role"]
        if not patch:
            raise ValueError("update_member requires display_name and/or role")
        return _OperationPlan(
            summary=f"Update member #{member_id} in family #{family_id}",
            method="PATCH",
            path=f"/families/{family_id}/members/{member_id}",
            body=patch,
        )
    if op_type == "delete_member":
        _required(payload, ["family_id", "member_id"], op_type)
        return _OperationPlan(
            summary=f"Delete member #{payload['member_id']} from family #{payload['family_id']}",
            method="DELETE",
            path=f"/families/{payload['family_id']}/members/{payload['member_id']}",
            destructive=True,
        )
    if op_type == "create_goal":
        _required(payload, ["family_id", "name", "description", "weight"], op_type)
        return _OperationPlan(
            summary=f"Create goal '{payload['name']}' for family #{payload['family_id']}",
            method="POST",
            path="/goals",
            body={
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
            },
        )
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
        return _OperationPlan(summary=f"Update goal #{payload['goal_id']}", method="PATCH", path=f"/goals/{payload['goal_id']}", body=patch)
    if op_type == "delete_goal":
        _required(payload, ["goal_id"], op_type)
        return _OperationPlan(summary=f"Delete goal #{payload['goal_id']}", method="DELETE", path=f"/goals/{payload['goal_id']}", destructive=True)
    if op_type == "create_decision":
        _required(payload, ["family_id", "title", "description"], op_type)
        return _OperationPlan(summary=f"Create decision '{payload['title']}'", method="POST", path="/decisions", body=payload)
    if op_type == "update_decision":
        _required(payload, ["decision_id"], op_type)
        patch = {key: value for key, value in payload.items() if key != "decision_id"}
        if not patch:
            raise ValueError("update_decision requires at least one mutable field")
        return _OperationPlan(
            summary=f"Update decision #{payload['decision_id']}",
            method="PATCH",
            path=f"/decisions/{payload['decision_id']}",
            body=patch,
        )
    if op_type == "delete_decision":
        _required(payload, ["decision_id"], op_type)
        return _OperationPlan(
            summary=f"Delete decision #{payload['decision_id']}",
            method="DELETE",
            path=f"/decisions/{payload['decision_id']}",
            destructive=True,
        )
    if op_type == "score_decision":
        _required(payload, ["decision_id", "goal_scores", "threshold_1_to_5"], op_type)
        decision_id = payload["decision_id"]
        body = {
            "goal_scores": payload["goal_scores"],
            "threshold_1_to_5": payload["threshold_1_to_5"],
            "computed_by": payload.get("computed_by", "human"),
        }
        return _OperationPlan(summary=f"Score decision #{decision_id}", method="POST", path=f"/decisions/{decision_id}/score", body=body)
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
        return _OperationPlan(summary=f"Create roadmap item for decision #{payload['decision_id']}", method="POST", path="/roadmap", body=body)
    if op_type == "update_roadmap_item":
        _required(payload, ["roadmap_id"], op_type)
        roadmap_id = payload["roadmap_id"]
        body = {key: value for key, value in payload.items() if key != "roadmap_id"}
        if not body:
            raise ValueError("update_roadmap_item requires at least one mutable field")
        return _OperationPlan(summary=f"Update roadmap item #{roadmap_id}", method="PATCH", path=f"/roadmap/{roadmap_id}", body=body)
    if op_type == "delete_roadmap_item":
        _required(payload, ["roadmap_id"], op_type)
        return _OperationPlan(summary=f"Delete roadmap item #{payload['roadmap_id']}", method="DELETE", path=f"/roadmap/{payload['roadmap_id']}", destructive=True)
    if op_type == "update_budget_policy":
        _required(payload, ["family_id", "threshold_1_to_5", "period_days", "default_allowance"], op_type)
        family_id = payload["family_id"]
        body = {
            "threshold_1_to_5": payload["threshold_1_to_5"],
            "period_days": payload["period_days"],
            "default_allowance": payload["default_allowance"],
            "person_allowances": payload.get("person_allowances", []),
        }
        return _OperationPlan(summary=f"Update budget policy for family #{family_id}", method="PUT", path=f"/budgets/families/{family_id}/policy", body=body)
    if op_type == "reset_budget_period":
        _required(payload, ["family_id"], op_type)
        return _OperationPlan(summary=f"Reset budget period for family #{payload['family_id']}", method="POST", path=f"/budgets/families/{payload['family_id']}/period/reset")

    raise ValueError(f"unsupported operation type: {op_type}")


def _proposal_output(proposal: Proposal) -> dict[str, Any]:
    return {
        "id": proposal.id,
        "actor_id": proposal.actor_id,
        "actor_name": proposal.actor_name,
        "rationale": proposal.rationale,
        "status": proposal.status,
        "allow_destructive": proposal.allow_destructive,
        "created_at": proposal.created_at,
        "confirmed_at": proposal.confirmed_at,
        "committed_at": proposal.committed_at,
        "operation_preview": proposal.operation_preview,
        "commit_results": proposal.commit_results,
    }


@mcp.tool()
def server_health() -> dict[str, Any]:
    """Verify MCP server and Decision API connectivity."""
    result = _request("GET", "/health", actor_id="mcp-system", actor_name=SERVER_NAME)
    return {"mcp_server": SERVER_NAME, "api_base": API_BASE, "api_health": result["body"]}


@mcp.tool()
def list_families(actor_id: str = "read-only") -> dict[str, Any]:
    """Read families."""
    return _request("GET", "/families", actor_id=actor_id, actor_name=SERVER_NAME)["body"]


@mcp.tool()
def list_family_members(family_id: int, actor_id: str = "read-only") -> dict[str, Any]:
    """Read members for a family."""
    return _request("GET", f"/families/{family_id}/members", actor_id=actor_id, actor_name=SERVER_NAME)["body"]


@mcp.tool()
def list_family_persons(family_id: int, actor_id: str = "read-only") -> dict[str, Any]:
    """Read canonical persons for a family."""
    return _request("GET", f"/families/{family_id}/persons", actor_id=actor_id, actor_name=SERVER_NAME)["body"]


@mcp.tool()
def get_resolved_context(
    family_id: int,
    actor_id: str,
    target_person_id: str | None = None,
    source_channel: str | None = None,
    source_sender_id: str | None = None,
) -> dict[str, Any]:
    """Resolve canonical family/person context for the current actor."""
    query: dict[str, Any] = {}
    if target_person_id is not None:
        query["target_person_id"] = target_person_id
    if source_channel is not None:
        query["source_channel"] = source_channel
    if source_sender_id is not None:
        query["source_sender_id"] = source_sender_id
    return _request("GET", f"/families/{family_id}/context", actor_id=actor_id, actor_name=SERVER_NAME, query=query)["body"]


@mcp.tool()
def resolve_person_alias(family_id: int, actor_id: str, alias: str) -> dict[str, Any]:
    """Resolve an alias or nickname to a canonical person."""
    return _request(
        "GET",
        f"/families/{family_id}/resolve-alias",
        actor_id=actor_id,
        actor_name=SERVER_NAME,
        query={"q": alias},
    )["body"]


@mcp.tool()
def resolve_sender_identity(family_id: int, actor_id: str, source_channel: str, source_sender_id: str) -> dict[str, Any]:
    """Resolve a channel sender mapping to a canonical person."""
    return _request(
        "POST",
        "/identity/resolve-sender",
        actor_id=actor_id,
        actor_name=SERVER_NAME,
        body={
            "family_id": family_id,
            "source_channel": source_channel,
            "source_sender_id": source_sender_id,
        },
    )["body"]


@mcp.tool()
def list_family_features(family_id: int, actor_id: str = "read-only") -> dict[str, Any]:
    """Read optional domain feature flags for a family."""
    return _request("GET", f"/families/{family_id}/features", actor_id=actor_id, actor_name=SERVER_NAME)["body"]


@mcp.tool()
def list_goals(
    family_id: int,
    actor_id: str = "read-only",
    scope_type: str | None = None,
    owner_person_id: str | None = None,
    status: str | None = None,
    include_deleted: bool = False,
) -> dict[str, Any]:
    """Read scoped goals for a family."""
    query: dict[str, Any] = {"family_id": family_id, "include_deleted": str(include_deleted).lower()}
    if scope_type is not None:
        query["scope_type"] = scope_type
    if owner_person_id is not None:
        query["owner_person_id"] = owner_person_id
    if status is not None:
        query["status"] = status
    return _request(
        "GET",
        "/goals",
        actor_id=actor_id,
        actor_name=SERVER_NAME,
        query=query,
    )["body"]


@mcp.tool()
def list_decisions(
    family_id: int,
    include_scores: bool = True,
    actor_id: str = "read-only",
    scope_type: str | None = None,
    owner_person_id: str | None = None,
    target_person_id: str | None = None,
    goal_policy: str | None = None,
    include_deleted: bool = False,
) -> dict[str, Any]:
    """Read scoped decisions for a family."""
    query: dict[str, Any] = {
        "family_id": family_id,
        "include_scores": str(include_scores).lower(),
        "include_deleted": str(include_deleted).lower(),
    }
    if scope_type is not None:
        query["scope_type"] = scope_type
    if owner_person_id is not None:
        query["owner_person_id"] = owner_person_id
    if target_person_id is not None:
        query["target_person_id"] = target_person_id
    if goal_policy is not None:
        query["goal_policy"] = goal_policy
    return _request(
        "GET",
        "/decisions",
        actor_id=actor_id,
        actor_name=SERVER_NAME,
        query=query,
    )["body"]


@mcp.tool()
def list_roadmap_items(family_id: int, actor_id: str = "read-only") -> dict[str, Any]:
    """Read roadmap items for a family."""
    return _request("GET", "/roadmap", actor_id=actor_id, actor_name=SERVER_NAME, query={"family_id": family_id})["body"]


@mcp.tool()
def get_budget_summary(family_id: int, actor_id: str = "read-only") -> dict[str, Any]:
    """Read discretionary budget summary for a family."""
    return _request("GET", f"/budgets/families/{family_id}", actor_id=actor_id, actor_name=SERVER_NAME)["body"]


@mcp.tool()
def get_decision(decision_id: int, actor_id: str = "read-only") -> dict[str, Any]:
    """Read a single decision."""
    return _request("GET", f"/decisions/{decision_id}", actor_id=actor_id, actor_name=SERVER_NAME)["body"]


@mcp.tool()
def get_decision_goal_context(decision_id: int, actor_id: str = "read-only") -> dict[str, Any]:
    """Read the active goal context used to score a decision."""
    return _request("GET", f"/decisions/{decision_id}/goal-context", actor_id=actor_id, actor_name=SERVER_NAME)["body"]


@mcp.tool()
def get_decision_score_runs(decision_id: int, actor_id: str = "read-only") -> dict[str, Any]:
    """Read score history for a decision."""
    return _request("GET", f"/decisions/{decision_id}/score-runs", actor_id=actor_id, actor_name=SERVER_NAME)["body"]


@mcp.tool()
def get_goal(goal_id: int, actor_id: str = "read-only") -> dict[str, Any]:
    """Read a single goal."""
    return _request("GET", f"/goals/{goal_id}", actor_id=actor_id, actor_name=SERVER_NAME)["body"]


@mcp.tool()
def get_family_dna(family_id: int, actor_id: str = "read-only") -> dict[str, Any]:
    """Read current family DNA snapshot."""
    return _request("GET", f"/family/{family_id}/dna", actor_id=actor_id, actor_name=SERVER_NAME)["body"]


@mcp.tool()
def search_family_memory(family_id: int, actor_id: str, query_text: str, top_k: int = 5) -> dict[str, Any]:
    """Search family memory."""
    return _request(
        "POST",
        f"/family/{family_id}/memory/search",
        actor_id=actor_id,
        actor_name=SERVER_NAME,
        body={"query": query_text, "top_k": top_k},
    )["body"]


@mcp.tool()
def write_family_memory(
    family_id: int,
    actor_id: str,
    memory_type: str,
    text: str,
    source_refs: list[dict[str, Any]] | None = None,
    owner_person_id: str | None = None,
    visibility_scope: str = "family",
) -> dict[str, Any]:
    """Write a family memory document."""
    return _request(
        "POST",
        f"/family/{family_id}/memory/documents",
        actor_id=actor_id,
        actor_name=SERVER_NAME,
        body={
            "family_id": family_id,
            "type": memory_type,
            "text": text,
            "source_refs": source_refs or [],
            "owner_person_id": owner_person_id,
            "visibility_scope": visibility_scope,
        },
    )["body"]


@mcp.tool()
def get_agent_session(family_id: int, agent_name: str, session_id: str, actor_id: str) -> dict[str, Any]:
    """Read domain agent session state."""
    return _request(
        "GET",
        f"/family/{family_id}/agents/{agent_name}/sessions/{session_id}",
        actor_id=actor_id,
        actor_name=SERVER_NAME,
    )["body"]


@mcp.tool()
def put_agent_session(
    family_id: int,
    agent_name: str,
    session_id: str,
    actor_id: str,
    state: dict[str, Any],
    status: str | None = None,
) -> dict[str, Any]:
    """Upsert domain agent session state."""
    return _request(
        "PUT",
        f"/family/{family_id}/agents/{agent_name}/sessions/{session_id}",
        actor_id=actor_id,
        actor_name=SERVER_NAME,
        body={"status": status, "state": state},
    )["body"]


@mcp.tool()
def delete_agent_session(family_id: int, agent_name: str, session_id: str, actor_id: str) -> dict[str, Any]:
    """Delete domain agent session state."""
    return _request(
        "DELETE",
        f"/family/{family_id}/agents/{agent_name}/sessions/{session_id}",
        actor_id=actor_id,
        actor_name=SERVER_NAME,
    )


@mcp.tool()
def search_notes(
    family_id: int,
    actor_id: str,
    query_text: str,
    top_k: int = 5,
    include_content: bool = True,
    owner_person_id: str | None = None,
) -> dict[str, Any]:
    """Search indexed notes."""
    return _file_request(
        "POST",
        "/notes/search",
        actor_id=actor_id,
        actor_name=SERVER_NAME,
        body={
            "family_id": family_id,
            "actor": actor_id,
            "query": query_text,
            "top_k": top_k,
            "include_content": include_content,
            "owner_person_id": owner_person_id,
        },
    )["body"]


@mcp.tool()
def search_documents(
    family_id: int,
    actor_id: str,
    query_text: str,
    top_k: int = 8,
    include_content: bool = True,
    owner_person_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    document_kinds: list[str] | None = None,
    preferred_item_types: list[str] | None = None,
    content_types: list[str] | None = None,
    query_tags: list[str] | None = None,
) -> dict[str, Any]:
    """Search indexed notes and files with unified hybrid retrieval."""
    return _file_request(
        "POST",
        "/search",
        actor_id=actor_id,
        actor_name=SERVER_NAME,
        body={
            "family_id": family_id,
            "actor": actor_id,
            "query": query_text,
            "top_k": top_k,
            "owner_person_id": owner_person_id,
            "date_from": date_from,
            "date_to": date_to,
            "document_kinds": document_kinds or [],
            "preferred_item_types": preferred_item_types or [],
            "content_types": content_types or [],
            "query_tags": query_tags or [],
            "include_content": include_content,
        },
    )["body"]


@mcp.tool()
def index_file_document(
    family_id: int,
    actor_id: str,
    path: str,
    item_type: str,
    role: str,
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
    """Index or update a file document for retrieval."""
    return _file_request(
        "POST",
        "/files/index",
        actor_id=actor_id,
        actor_name=SERVER_NAME,
        body={
            "family_id": family_id,
            "actor": actor_id,
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
    )["body"]


@mcp.tool()
def search_files(
    family_id: int,
    actor_id: str,
    query_text: str,
    top_k: int = 5,
    include_content: bool = True,
    preferred_item_types: list[str] | None = None,
    content_types: list[str] | None = None,
    owner_person_id: str | None = None,
) -> dict[str, Any]:
    """Search indexed files across notes, documents, and media."""
    return _file_request(
        "POST",
        "/files/search",
        actor_id=actor_id,
        actor_name=SERVER_NAME,
        body={
            "family_id": family_id,
            "actor": actor_id,
            "query": query_text,
            "top_k": top_k,
            "include_content": include_content,
            "preferred_item_types": preferred_item_types or [],
            "content_types": content_types or [],
            "owner_person_id": owner_person_id,
        },
    )["body"]


@mcp.tool()
def record_family_event(event: dict[str, Any], actor_id: str, actor_name: str | None = None) -> dict[str, Any]:
    """Record a canonical family event into the shared Family Cloud backend."""
    return _event_request(
        "POST",
        "/events",
        actor_id=actor_id,
        actor_name=actor_name or SERVER_NAME,
        body=event,
    )["body"]


@mcp.tool()
def list_family_events(
    family_id: int,
    actor_id: str,
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
) -> list[dict[str, Any]]:
    """Read canonical family events."""
    query: dict[str, Any] = {"family_id": family_id, "limit": limit, "offset": offset}
    if domain is not None:
        query["domain"] = domain
    if domains:
        query["domains"] = domains
    if event_type is not None:
        query["event_type"] = event_type
    if tag is not None:
        query["tag"] = tag
    if subject_id is not None:
        query["subject_id"] = subject_id
    if actor_filter is not None:
        query["actor_id"] = actor_filter
    if start is not None:
        query["start"] = start
    if end is not None:
        query["end"] = end
    return _event_request("GET", "/events", actor_id=actor_id, actor_name=SERVER_NAME, query=query)["body"]


@mcp.tool()
def get_family_timeline(
    family_id: int,
    actor_id: str,
    domain: str | None = None,
    domains: list[str] | None = None,
    event_type: str | None = None,
    tag: str | None = None,
    start: str | None = None,
    end: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Read normalized canonical timeline items for a family."""
    query: dict[str, Any] = {"family_id": family_id, "limit": limit}
    if domain is not None:
        query["domain"] = domain
    if domains:
        query["domains"] = domains
    if event_type is not None:
        query["event_type"] = event_type
    if tag is not None:
        query["tag"] = tag
    if start is not None:
        query["start"] = start
    if end is not None:
        query["end"] = end
    return _event_request("GET", "/timeline", actor_id=actor_id, actor_name=SERVER_NAME, query=query)["body"]


@mcp.tool()
def get_family_event_counts(
    family_id: int,
    actor_id: str,
    domain: str | None = None,
    domains: list[str] | None = None,
    event_type: str | None = None,
    tag: str | None = None,
    start: str | None = None,
    end: str | None = None,
) -> list[dict[str, Any]]:
    """Read canonical family event aggregate counts."""
    query: dict[str, Any] = {"family_id": family_id}
    if domain is not None:
        query["domain"] = domain
    if domains:
        query["domains"] = domains
    if event_type is not None:
        query["event_type"] = event_type
    if tag is not None:
        query["tag"] = tag
    if start is not None:
        query["start"] = start
    if end is not None:
        query["end"] = end
    return _event_request("GET", "/analytics/counts", actor_id=actor_id, actor_name=SERVER_NAME, query=query)["body"]


@mcp.tool()
def get_family_event_time_series(
    family_id: int,
    actor_id: str,
    metric: str,
    bucket: str,
    domain: str | None = None,
    domains: list[str] | None = None,
    event_type: str | None = None,
    tag: str | None = None,
    start: str | None = None,
    end: str | None = None,
) -> dict[str, Any]:
    """Read canonical family event time-series metrics."""
    query: dict[str, Any] = {"family_id": family_id, "metric": metric, "bucket": bucket}
    if domain is not None:
        query["domain"] = domain
    if domains:
        query["domains"] = domains
    if event_type is not None:
        query["event_type"] = event_type
    if tag is not None:
        query["tag"] = tag
    if start is not None:
        query["start"] = start
    if end is not None:
        query["end"] = end
    return _event_request("GET", "/analytics/time-series", actor_id=actor_id, actor_name=SERVER_NAME, query=query)["body"]


@mcp.tool()
def get_family_event_domain_summary(
    family_id: int,
    actor_id: str,
    start: str | None = None,
    end: str | None = None,
) -> list[dict[str, Any]]:
    """Read per-domain family event activity summary."""
    query: dict[str, Any] = {"family_id": family_id}
    if start is not None:
        query["start"] = start
    if end is not None:
        query["end"] = end
    return _event_request("GET", "/analytics/domain-summary", actor_id=actor_id, actor_name=SERVER_NAME, query=query)["body"]


@mcp.tool()
def compare_family_event_periods(
    family_id: int,
    actor_id: str,
    metric: str,
    current_start: str,
    current_end: str,
    baseline_start: str,
    baseline_end: str,
    domain: str | None = None,
    domains: list[str] | None = None,
    event_type: str | None = None,
    tag: str | None = None,
) -> dict[str, Any]:
    """Compare a family event metric across two periods."""
    query: dict[str, Any] = {
        "family_id": family_id,
        "metric": metric,
        "current_start": current_start,
        "current_end": current_end,
        "baseline_start": baseline_start,
        "baseline_end": baseline_end,
    }
    if domain is not None:
        query["domain"] = domain
    if domains:
        query["domains"] = domains
    if event_type is not None:
        query["event_type"] = event_type
    if tag is not None:
        query["tag"] = tag
    return _event_request("GET", "/analytics/compare-periods", actor_id=actor_id, actor_name=SERVER_NAME, query=query)["body"]


@mcp.tool()
def get_family_event_sequences(
    family_id: int,
    actor_id: str,
    anchor_event_id: str | None = None,
    anchor_occurred_at: str | None = None,
    domain: str | None = None,
    domains: list[str] | None = None,
    before_limit: int = 5,
    after_limit: int = 5,
) -> dict[str, Any]:
    """Read before/after family event sequences around an anchor event or date."""
    query: dict[str, Any] = {
        "family_id": family_id,
        "before_limit": before_limit,
        "after_limit": after_limit,
    }
    if anchor_event_id is not None:
        query["anchor_event_id"] = anchor_event_id
    if anchor_occurred_at is not None:
        query["anchor_occurred_at"] = anchor_occurred_at
    if domain is not None:
        query["domain"] = domain
    if domains:
        query["domains"] = domains
    return _event_request("GET", "/analytics/sequences", actor_id=actor_id, actor_name=SERVER_NAME, query=query)["body"]


@mcp.tool()
def get_family_event_top_tags(
    family_id: int,
    actor_id: str,
    start: str | None = None,
    end: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Read top event tags and bounded payload topics."""
    query: dict[str, Any] = {"family_id": family_id, "limit": limit}
    if start is not None:
        query["start"] = start
    if end is not None:
        query["end"] = end
    return _event_request("GET", "/analytics/top-tags", actor_id=actor_id, actor_name=SERVER_NAME, query=query)["body"]


@mcp.tool()
def get_family_event_data_quality(
    family_id: int,
    actor_id: str,
    start: str | None = None,
    end: str | None = None,
) -> dict[str, Any]:
    """Read family event data quality summary."""
    query: dict[str, Any] = {"family_id": family_id}
    if start is not None:
        query["start"] = start
    if end is not None:
        query["end"] = end
    return _event_request("GET", "/analytics/data-quality", actor_id=actor_id, actor_name=SERVER_NAME, query=query)["body"]


@mcp.tool()
def propose_family_dna_patch(
    family_id: int,
    actor_id: str,
    rationale: str,
    patch: list[dict[str, Any]],
    confidence: float = 0.5,
    sources: list[str] | None = None,
) -> dict[str, Any]:
    """Propose a family DNA patch."""
    return _request(
        "POST",
        f"/family/{family_id}/dna/propose",
        actor_id=actor_id,
        actor_name=SERVER_NAME,
        body={"patch": patch, "rationale": rationale, "confidence": confidence, "sources": sources or []},
    )["body"]


@mcp.tool()
def commit_family_dna_patch(family_id: int, proposal_id: str, actor_id: str) -> dict[str, Any]:
    """Commit a previously proposed family DNA patch."""
    return _request(
        "POST",
        f"/family/{family_id}/dna/commit/{proposal_id}",
        actor_id=actor_id,
        actor_name=SERVER_NAME,
    )["body"]


@mcp.tool()
def create_agent_question(
    family_id: int,
    actor_id: str,
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
) -> dict[str, Any]:
    """Create or update a queued agent question."""
    return _question_request(
        "POST",
        f"/families/{family_id}/questions",
        actor_id=actor_id,
        actor_name=SERVER_NAME,
        body={
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
    )["body"]


@mcp.tool()
def list_agent_questions(
    family_id: int,
    actor_id: str,
    domain: str | None = None,
    status: str | None = None,
    include_inactive: bool = False,
) -> dict[str, Any]:
    """List queued agent questions."""
    query = {"include_inactive": str(include_inactive).lower()}
    if domain is not None:
        query["domain"] = domain
    if status is not None:
        query["status"] = status
    return _question_request(
        "GET",
        f"/families/{family_id}/questions",
        actor_id=actor_id,
        actor_name=SERVER_NAME,
        query=query,
    )["body"]


@mcp.tool()
def update_agent_question(
    family_id: int,
    question_id: str,
    actor_id: str,
    status: str | None = None,
    summary: str | None = None,
    prompt: str | None = None,
    answer_sufficiency_state: str | None = None,
    context_patch: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Patch a queued agent question."""
    body: dict[str, Any] = {"context_patch": context_patch or {}}
    if status is not None:
        body["status"] = status
    if summary is not None:
        body["summary"] = summary
    if prompt is not None:
        body["prompt"] = prompt
    if answer_sufficiency_state is not None:
        body["answer_sufficiency_state"] = answer_sufficiency_state
    return _question_request(
        "PATCH",
        f"/families/{family_id}/questions/{question_id}",
        actor_id=actor_id,
        actor_name=SERVER_NAME,
        body=body,
    )["body"]


@mcp.tool()
def claim_agent_question(family_id: int, actor_id: str, agent_name: str, channel: str = "discord_dm", force: bool = False) -> dict[str, Any]:
    """Claim the next eligible queued question for proactive delivery."""
    return _question_request(
        "POST",
        f"/families/{family_id}/questions/claim-next",
        actor_id=actor_id,
        actor_name=SERVER_NAME,
        body={"agent_id": agent_name, "channel": channel, "force": force},
    )["body"]


@mcp.tool()
def mark_agent_question_asked(
    family_id: int,
    question_id: str,
    actor_id: str,
    delivery_agent: str,
    delivery_channel: str = "discord_dm",
    claim_token: str | None = None,
) -> dict[str, Any]:
    """Mark a queued question as asked by a top-level agent."""
    return _question_request(
        "POST",
        f"/families/{family_id}/questions/{question_id}/asked",
        actor_id=actor_id,
        actor_name=SERVER_NAME,
        body={"delivery_agent": delivery_agent, "delivery_channel": delivery_channel, "claim_token": claim_token, "delivery_context": {}},
    )["body"]


@mcp.tool()
def answer_agent_question(
    family_id: int,
    question_id: str,
    actor_id: str,
    answer_text: str,
    status: str = "resolved",
) -> dict[str, Any]:
    """Store a user answer for a queued question."""
    return _question_request(
        "POST",
        f"/families/{family_id}/questions/{question_id}/answer",
        actor_id=actor_id,
        actor_name=SERVER_NAME,
        body={"answer_text": answer_text, "status": status},
    )["body"]


@mcp.tool()
def resolve_agent_question(
    family_id: int,
    question_id: str,
    actor_id: str,
    status: str = "resolved",
    resolution_note: str | None = None,
    answer_sufficiency_state: str | None = None,
) -> dict[str, Any]:
    """Resolve, dismiss, expire, or partially answer a queued question."""
    body: dict[str, Any] = {"status": status, "context_patch": {}}
    if resolution_note is not None:
        body["resolution_note"] = resolution_note
    if answer_sufficiency_state is not None:
        body["answer_sufficiency_state"] = answer_sufficiency_state
    return _question_request(
        "POST",
        f"/families/{family_id}/questions/{question_id}/resolve",
        actor_id=actor_id,
        actor_name=SERVER_NAME,
        body=body,
    )["body"]


@mcp.tool()
def record_agent_event(
    family_id: int,
    actor_id: str,
    domain: str,
    source_agent: str,
    event_type: str,
    summary: str,
    topic: str | None = None,
    status: str | None = None,
    value_number: float | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record shared telemetry and playback event."""
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
    return _request(
        "POST",
        f"/family/{family_id}/ops/events",
        actor_id=actor_id,
        actor_name=SERVER_NAME,
        body=body,
    )["body"]


@mcp.tool()
def query_agent_metrics(
    family_id: int,
    actor_id: str,
    domain: str | None = None,
    metric_keys: list[str] | None = None,
    start_at: str | None = None,
    end_at: str | None = None,
) -> dict[str, Any]:
    """Query shared agent metrics."""
    body: dict[str, Any] = {"metric_keys": metric_keys or []}
    if domain is not None:
        body["domain"] = domain
    if start_at is not None:
        body["start_at"] = start_at
    if end_at is not None:
        body["end_at"] = end_at
    return _request(
        "POST",
        f"/family/{family_id}/ops/metrics/query",
        actor_id=actor_id,
        actor_name=SERVER_NAME,
        body=body,
    )["body"]


@mcp.tool()
def get_playback_timeline(
    family_id: int,
    actor_id: str,
    domain: str | None = None,
    event_types: list[str] | None = None,
    start_at: str | None = None,
    end_at: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Query playback timeline events."""
    body: dict[str, Any] = {"event_types": event_types or [], "limit": limit}
    if domain is not None:
        body["domain"] = domain
    if start_at is not None:
        body["start_at"] = start_at
    if end_at is not None:
        body["end_at"] = end_at
    return _request(
        "POST",
        f"/family/{family_id}/ops/playback/query",
        actor_id=actor_id,
        actor_name=SERVER_NAME,
        body=body,
    )["body"]


@mcp.tool()
def propose_changes(
    actor_id: str,
    rationale: str,
    operations: list[Operation],
    actor_name: str | None = None,
    allow_destructive: bool = False,
) -> dict[str, Any]:
    """Stage mutable changes. Nothing is persisted until confirm + commit."""
    if not operations:
        raise ValueError("operations must not be empty")

    plans = [_to_plan(op) for op in operations]
    destructive = any(plan.destructive for plan in plans)
    if destructive and not allow_destructive:
        raise ValueError("proposal includes destructive operation(s). Re-run with allow_destructive=true after explicit user confirmation.")

    proposal = Proposal(
        id=str(uuid.uuid4()),
        actor_id=actor_id,
        actor_name=actor_name,
        rationale=rationale,
        operations=operations,
        operation_preview=[plan.summary for plan in plans],
        allow_destructive=allow_destructive,
        created_at=_now_iso(),
    )

    with _proposal_lock:
        _proposals[proposal.id] = proposal
    _append_audit_event("proposal_created", _proposal_output(proposal))
    return _proposal_output(proposal)


@mcp.tool()
def get_proposal(proposal_id: str) -> dict[str, Any]:
    """Fetch current proposal state."""
    with _proposal_lock:
        proposal = _proposals.get(proposal_id)
    if proposal is None:
        raise ValueError(f"proposal not found: {proposal_id}")
    return _proposal_output(proposal)


@mcp.tool()
def confirm_proposal(proposal_id: str, actor_id: str, confirmation_note: str) -> dict[str, Any]:
    """Confirm a staged proposal before commit."""
    with _proposal_lock:
        proposal = _proposals.get(proposal_id)
        if proposal is None:
            raise ValueError(f"proposal not found: {proposal_id}")
        if proposal.status != "proposed":
            raise ValueError(f"proposal status is {proposal.status}; only proposed items can be confirmed")
        if proposal.actor_id != actor_id:
            raise ValueError("actor_id must match proposal owner")
        proposal.status = "confirmed"
        proposal.confirmed_at = _now_iso()
        _proposals[proposal_id] = proposal

    _append_audit_event(
        "proposal_confirmed",
        {
            "proposal_id": proposal_id,
            "actor_id": actor_id,
            "confirmation_note": confirmation_note,
            "confirmed_at": proposal.confirmed_at,
        },
    )
    return _proposal_output(proposal)


@mcp.tool()
def cancel_proposal(proposal_id: str, actor_id: str, reason: str) -> dict[str, Any]:
    """Cancel a staged proposal."""
    with _proposal_lock:
        proposal = _proposals.get(proposal_id)
        if proposal is None:
            raise ValueError(f"proposal not found: {proposal_id}")
        if proposal.status in {"committed", "canceled"}:
            raise ValueError(f"proposal already {proposal.status}")
        if proposal.actor_id != actor_id:
            raise ValueError("actor_id must match proposal owner")
        proposal.status = "canceled"
        _proposals[proposal_id] = proposal

    _append_audit_event("proposal_canceled", {"proposal_id": proposal_id, "actor_id": actor_id, "reason": reason})
    return _proposal_output(proposal)


@mcp.tool()
def commit_proposal(proposal_id: str, actor_id: str) -> dict[str, Any]:
    """Persist a confirmed proposal as atomic, ordered API calls."""
    with _proposal_lock:
        proposal = _proposals.get(proposal_id)
        if proposal is None:
            raise ValueError(f"proposal not found: {proposal_id}")
        if proposal.status != "confirmed":
            raise ValueError(f"proposal status is {proposal.status}; only confirmed items can be committed")
        if proposal.actor_id != actor_id:
            raise ValueError("actor_id must match proposal owner")

    plans = [_to_plan(op) for op in proposal.operations]
    results: list[dict[str, Any]] = []
    for index, plan in enumerate(plans, start=1):
        result = _request(plan.method, plan.path, actor_id=proposal.actor_id, actor_name=proposal.actor_name, body=plan.body)
        results.append(
            {
                "index": index,
                "summary": plan.summary,
                "request": {"method": plan.method, "path": plan.path, "body": plan.body},
                "response": result,
            }
        )

    with _proposal_lock:
        proposal = _proposals[proposal_id]
        proposal.status = "committed"
        proposal.committed_at = _now_iso()
        proposal.commit_results = results
        _proposals[proposal_id] = proposal

    _append_audit_event("proposal_committed", _proposal_output(proposal))
    return _proposal_output(proposal)


if __name__ == "__main__":
    mcp.run()
