from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agents.common.mcp.client import HttpToolClient


@dataclass
class DecisionSystemTools:
    """
    Thin tool adapter for the Decision System.

    This currently uses direct HTTP calls to the decision API to keep the agent runnable
    while a first-class MCP client transport is implemented.
    """

    http: HttpToolClient

    def get_family_goals(self, family_id: int, *, actor_email: str | None = None) -> list[dict[str, Any]]:
        headers = {"X-Dev-User": actor_email} if actor_email else None
        return self.http.request("GET", "/goals", params={"family_id": family_id}, headers=headers).result["items"]

    def list_roadmap_items(self, family_id: int, *, actor_email: str | None = None) -> list[dict[str, Any]]:
        headers = {"X-Dev-User": actor_email} if actor_email else None
        return self.http.request("GET", "/roadmap", params={"family_id": family_id}, headers=headers).result["items"]

    def create_decision(self, payload: dict[str, Any], *, actor_email: str | None = None) -> dict[str, Any]:
        headers = {"X-Dev-User": actor_email} if actor_email else None
        return self.http.request("POST", "/decisions", json_body=payload, headers=headers).result

    def update_decision(self, decision_id: int, patch: dict[str, Any], *, actor_email: str | None = None) -> dict[str, Any]:
        headers = {"X-Dev-User": actor_email} if actor_email else None
        return self.http.request("PATCH", f"/decisions/{decision_id}", json_body=patch, headers=headers).result

    def score_decision(self, decision_id: int, payload: dict[str, Any], *, actor_email: str | None = None) -> dict[str, Any]:
        headers = {"X-Dev-User": actor_email} if actor_email else None
        return self.http.request("POST", f"/decisions/{decision_id}/score", json_body=payload, headers=headers).result

    def add_to_roadmap(self, payload: dict[str, Any], *, actor_email: str | None = None) -> dict[str, Any]:
        headers = {"X-Dev-User": actor_email} if actor_email else None
        return self.http.request("POST", "/roadmap", json_body=payload, headers=headers).result

    def get_upcoming_roadmap_items(self, family_id: int, days: int = 30) -> list[dict[str, Any]]:
        # Existing API doesn't expose server-side windowing; agent filters client-side.
        return self.list_roadmap_items(family_id)

    def write_memory(self, family_id: int, type: str, text: str, *, actor_email: str | None = None) -> dict[str, Any]:
        headers = {"X-Dev-User": actor_email} if actor_email else None
        return self.http.request(
            "POST",
            f"/family/{family_id}/memory/documents",
            json_body={"family_id": family_id, "type": type, "text": text, "source_refs": []},
            headers=headers,
        ).result
