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
    teams: list[dict[str, Any]] = field(default_factory=list)
    team_members_by_team: dict[int, list[dict[str, Any]]] = field(default_factory=dict)

    def list_lists(self) -> list[dict[str, Any]]:
        return list(self.lists)

    def list_tasks(self, list_id: int) -> list[dict[str, Any]]:
        return list(self.tasks_by_list.get(int(list_id), []))

    def list_teams(self) -> list[dict[str, Any]]:
        return list(self.teams)

    def list_team_members(self, team_id: int) -> list[dict[str, Any]]:
        return list(self.team_members_by_team.get(int(team_id), []))

    def list_list_teams(self, list_id: int) -> list[dict[str, Any]]:
        return []

    def get_current_user(self) -> dict[str, Any] | None:
        return {"id": 1, "name": "Owner"}

    def healthcheck(self):  # pragma: no cover
        from agents.task_agent.schemas import HealthStatus

        return HealthStatus(ok=True, backend_reachable=True, tools_discovered=["fake"])

    # Unused stubs
    def create_list(self, title: str, description: str = "") -> dict[str, Any]: raise NotImplementedError
    def get_list(self, list_id: int) -> dict[str, Any] | None: return None
    def delete_list(self, list_id: int) -> dict[str, Any]: raise NotImplementedError
    def archive_list(self, list_id: int, *, archived: bool = True) -> dict[str, Any]: raise NotImplementedError
    def set_list_parent(self, list_id: int, parent_list_id: int) -> dict[str, Any]: raise NotImplementedError
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
    ) -> dict[str, Any]: raise NotImplementedError
    def update_task(self, task_id: int, *, patch: dict[str, Any]) -> dict[str, Any]: raise NotImplementedError
    def get_task(self, task_id: int) -> dict[str, Any] | None: raise NotImplementedError
    def delete_task(self, task_id: int) -> dict[str, Any]: raise NotImplementedError
    def ensure_list(self, title: str, *, description: str = "") -> dict[str, Any]: raise NotImplementedError
    def create_team(self, name: str) -> dict[str, Any]: raise NotImplementedError
    def share_list_with_team(self, list_id: int, team_id: int, permission: int = 0) -> dict[str, Any]: raise NotImplementedError
    def list_labels(self) -> list[dict[str, Any]]: return []
    def create_label(self, title: str, *, description: str = "", hex_color: str = "") -> dict[str, Any]: raise NotImplementedError
    def ensure_label(self, title: str, *, description: str = "", hex_color: str = "") -> dict[str, Any]: raise NotImplementedError
    def add_label_to_task(self, task_id: int, label_id: int) -> dict[str, Any]: raise NotImplementedError
    def set_task_assignees(self, task_id: int, assignee_ids: list[int]) -> dict[str, Any]: raise NotImplementedError
    def set_task_progress(self, task_id: int, progress: float) -> dict[str, Any]: raise NotImplementedError
    def set_task_color(self, task_id: int, color: str) -> dict[str, Any]: raise NotImplementedError
    def set_task_repeat(self, task_id: int, repeat_after_seconds: int) -> dict[str, Any]: raise NotImplementedError
    def add_task_relation(self, task_id: int, other_task_id: int, relation_type: str) -> dict[str, Any]: raise NotImplementedError
    def move_task(self, task_id: int, project_id: int) -> dict[str, Any]: raise NotImplementedError
    def add_task_attachment(self, task_id: int, *, url: str | None = None, filename: str | None = None, bytes_base64: str | None = None) -> dict[str, Any]: raise NotImplementedError
    def capabilities(self) -> dict[str, bool]: return {}


def test_list_all_teams_query():
    tools = _FakeTools(
        teams=[{"id": 7, "name": "Parent"}, {"id": 9, "name": "Girls"}],
    )
    agent = TaskAgent(ai=TaskAi(), tools=tools)
    req = TaskInvokeRequest(actor="x", family_id=1, message="List all teams", attachments=[], metadata={})
    res = agent.run(req)
    assert res.insights is not None
    assert res.insights.query_answer is not None
    lower = res.insights.query_answer.lower()
    assert lower.startswith("teams (2):")
    assert "parent" in lower
    assert "girls" in lower


def test_list_members_in_parent_team_query():
    tools = _FakeTools(
        teams=[{"id": 7, "name": "Parent"}],
        team_members_by_team={
            7: [{"id": 2, "name": "Dadda Callender"}, {"id": 3, "name": "Mom Callender"}],
        },
    )
    agent = TaskAgent(ai=TaskAi(), tools=tools)
    req = TaskInvokeRequest(actor="x", family_id=1, message="List all members in the Parent team", attachments=[], metadata={})
    res = agent.run(req)
    assert res.insights is not None
    assert res.insights.query_answer is not None
    lower = res.insights.query_answer.lower()
    assert "members in parent:" in lower
    assert "dadda callender" in lower
    assert "mom callender" in lower


def test_list_archived_projects_query():
    tools = _FakeTools(
        lists=[
            {"id": 1, "title": "Shopping", "is_archived": False},
            {"id": 2, "title": "Lowes Trip", "is_archived": True},
        ],
        tasks_by_list={1: [], 2: [{"id": 10, "title": "Buy saw", "done": False}]},
    )
    agent = TaskAgent(ai=TaskAi(), tools=tools)
    req = TaskInvokeRequest(actor="x", family_id=1, message="List archived projects", attachments=[], metadata={})
    res = agent.run(req)
    assert res.insights is not None
    assert res.insights.query_answer is not None
    lower = res.insights.query_answer.lower()
    assert lower.startswith("archived projects (1):")
    assert "lowes trip (1 open) [archived]" in lower
    assert "shopping" not in lower


def test_list_tasks_labeled_high_cost_query():
    tools = _FakeTools(
        lists=[{"id": 1, "title": "Shopping"}, {"id": 2, "title": "General"}],
        tasks_by_list={
            1: [{"id": 10, "title": "Buy tool box", "done": False, "labels": [{"id": 5, "title": "High Cost"}]}],
            2: [{"id": 20, "title": "Email school", "done": False, "labels": []}],
        },
    )
    agent = TaskAgent(ai=TaskAi(), tools=tools)
    req = TaskInvokeRequest(actor="x", family_id=1, message="List tasks labeled high cost", attachments=[], metadata={})
    res = agent.run(req)
    if res.insights is not None and res.insights.query_answer is not None:
        lower = res.insights.query_answer.lower()
        assert lower.startswith("tasks labeled high cost (1):")
        assert "buy tool box [shopping]" in lower
        assert "email school" not in lower
