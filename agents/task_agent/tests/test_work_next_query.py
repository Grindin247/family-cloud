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
    list_teams_by_list: dict[int, list[dict[str, Any]]] = field(default_factory=dict)
    current_user: dict[str, Any] = field(default_factory=lambda: {"id": 3, "name": "Dadda Callender", "username": "dadda"})

    def list_lists(self) -> list[dict[str, Any]]:
        return list(self.lists)

    def list_tasks(self, list_id: int) -> list[dict[str, Any]]:
        return list(self.tasks_by_list.get(int(list_id), []))

    def list_teams(self) -> list[dict[str, Any]]:
        return list(self.teams)

    def list_team_members(self, team_id: int) -> list[dict[str, Any]]:
        return list(self.team_members_by_team.get(int(team_id), []))

    def list_list_teams(self, list_id: int) -> list[dict[str, Any]]:
        return list(self.list_teams_by_list.get(int(list_id), []))

    def get_current_user(self) -> dict[str, Any] | None:
        return dict(self.current_user)

    # Unused stubs
    def healthcheck(self):  # pragma: no cover
        from agents.task_agent.schemas import HealthStatus

        return HealthStatus(ok=True, backend_reachable=True, tools_discovered=["fake"])

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


def test_work_next_query_includes_assigned_and_team_project_tasks_for_person():
    tools = _FakeTools(
        lists=[{"id": 1, "title": "Shopping"}, {"id": 2, "title": "Garden"}],
        tasks_by_list={
            1: [{"id": 10, "title": "Buy milk", "done": False, "assignees": [{"id": 42, "name": "Felicity Jones"}]}],
            2: [{"id": 20, "title": "Trim hedges", "done": False, "assignees": []}],
        },
        teams=[{"id": 7, "name": "Home Ops"}],
        team_members_by_team={7: [{"id": 42, "name": "Felicity Jones"}]},
        list_teams_by_list={2: [{"id": 7, "name": "Home Ops"}]},
    )
    agent = TaskAgent(ai=TaskAi(), tools=tools)
    req = TaskInvokeRequest(
        actor="u@example.com",
        family_id=1,
        message="what tasks should Felicity work next",
        attachments=[],
        metadata={},
    )
    res = agent.run(req)
    assert res.status == "executed"
    assert res.intent == "insights_only"
    assert res.insights is not None
    assert res.insights.query_answer is not None
    lower = res.insights.query_answer.lower()
    assert "felicity should work on" in lower
    assert "buy milk" in lower
    assert "trim hedges" in lower


def test_work_next_query_falls_back_to_suggested_open_tasks_when_no_direct_matches():
    tools = _FakeTools(
        lists=[{"id": 1, "title": "Felicity Admin"}, {"id": 2, "title": "General"}],
        tasks_by_list={
            1: [{"id": 30, "title": "Review Felicity schedule", "done": False, "assignees": []}],
            2: [{"id": 31, "title": "Pay electricity bill", "done": False, "assignees": []}],
        },
        teams=[],
        team_members_by_team={},
        list_teams_by_list={},
    )
    agent = TaskAgent(ai=TaskAi(), tools=tools)
    req = TaskInvokeRequest(
        actor="u@example.com",
        family_id=1,
        message="what tasks should Felicity work next",
        attachments=[],
        metadata={},
    )
    res = agent.run(req)
    assert res.status == "executed"
    assert res.insights is not None
    assert res.insights.query_answer is not None
    lower = res.insights.query_answer.lower()
    assert "review felicity schedule" in lower
    assert "pay electricity bill" not in lower
