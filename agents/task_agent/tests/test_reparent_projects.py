from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agents.task_agent.agent import TaskAgent
from agents.task_agent.ai import TaskAi
from agents.task_agent.schemas import TaskInvokeRequest


@dataclass
class _FakeTools:
    lists: list[dict[str, Any]] = field(default_factory=list)
    tasks_by_list: dict[int, list[dict[str, Any]]] = field(default_factory=dict)

    def list_lists(self) -> list[dict[str, Any]]:
        return list(self.lists)

    def list_tasks(self, list_id: int) -> list[dict[str, Any]]:
        return list(self.tasks_by_list.get(int(list_id), []))

    def set_list_parent(self, list_id: int, parent_list_id: int) -> dict[str, Any]:
        for item in self.lists:
            if int(item.get("id")) == int(list_id):
                item["parent_project_id"] = int(parent_list_id)
                return dict(item)
        return {"id": int(list_id), "parent_project_id": int(parent_list_id)}

    # Unused methods required by agent paths.
    def healthcheck(self):
        from agents.task_agent.schemas import HealthStatus

        return HealthStatus(ok=True, backend_reachable=True, tools_discovered=["fake"])

    def create_list(self, title: str, description: str = "") -> dict[str, Any]:
        raise NotImplementedError

    def get_list(self, list_id: int) -> dict[str, Any] | None:
        return None

    def delete_list(self, list_id: int) -> dict[str, Any]:
        raise NotImplementedError

    def archive_list(self, list_id: int, *, archived: bool = True) -> dict[str, Any]:
        raise NotImplementedError

    def create_task(
        self,
        list_id: int,
        *,
        title: str,
        description: str = "",
        done: bool = False,
        due_date: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        priority: int | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError

    def update_task(self, task_id: int, *, patch: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def get_task(self, task_id: int) -> dict[str, Any] | None:
        raise NotImplementedError

    def delete_task(self, task_id: int) -> dict[str, Any]:
        raise NotImplementedError

    def ensure_list(self, title: str, *, description: str = "") -> dict[str, Any]:
        raise NotImplementedError

    def get_current_user(self) -> dict[str, Any] | None:
        return None

    def list_teams(self) -> list[dict[str, Any]]:
        return []

    def create_team(self, name: str) -> dict[str, Any]:
        raise NotImplementedError

    def share_list_with_team(self, list_id: int, team_id: int, permission: int = 0) -> dict[str, Any]:
        raise NotImplementedError

    def list_labels(self) -> list[dict[str, Any]]:
        return []

    def create_label(self, title: str, *, description: str = "", hex_color: str = "") -> dict[str, Any]:
        raise NotImplementedError

    def ensure_label(self, title: str, *, description: str = "", hex_color: str = "") -> dict[str, Any]:
        raise NotImplementedError

    def add_label_to_task(self, task_id: int, label_id: int) -> dict[str, Any]:
        raise NotImplementedError

    def set_task_assignees(self, task_id: int, assignee_ids: list[int]) -> dict[str, Any]:
        raise NotImplementedError

    def set_task_progress(self, task_id: int, progress: float) -> dict[str, Any]:
        raise NotImplementedError

    def set_task_color(self, task_id: int, color: str) -> dict[str, Any]:
        raise NotImplementedError

    def set_task_repeat(self, task_id: int, repeat_after_seconds: int) -> dict[str, Any]:
        raise NotImplementedError

    def add_task_relation(self, task_id: int, other_task_id: int, relation_type: str) -> dict[str, Any]:
        raise NotImplementedError

    def move_task(self, task_id: int, project_id: int) -> dict[str, Any]:
        raise NotImplementedError

    def add_task_attachment(self, task_id: int, *, url: str | None = None, filename: str | None = None, bytes_base64: str | None = None) -> dict[str, Any]:
        raise NotImplementedError

    def capabilities(self) -> dict[str, bool]:
        return {}


def _build_agent() -> tuple[TaskAgent, _FakeTools]:
    tools = _FakeTools(
        lists=[
            {"id": 1, "title": "Shopping", "parent_project_id": 0},
            {"id": 2, "title": "Chores", "parent_project_id": 0},
        ],
        tasks_by_list={1: [], 2: []},
    )
    return TaskAgent(ai=TaskAi(), tools=tools), tools


def test_reparent_project_prompts():
    prompts = [
        "Set parent project for shopping Chores",
        "Move shopping under Chores",
        "Put shopping under chores",
    ]
    for prompt in prompts:
        agent, tools = _build_agent()
        req = TaskInvokeRequest(actor="u@example.com", family_id=1, message=prompt, attachments=[], metadata={})
        res = agent.run(req)
        assert res.status == "needs_input"
        assert res.mode == "extract"
        shopping = next(item for item in tools.lists if int(item["id"]) == 1)
        assert int(shopping.get("parent_project_id", 0)) == 0
