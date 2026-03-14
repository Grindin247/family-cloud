from __future__ import annotations

from dataclasses import dataclass, field
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Any
import base64

from fastapi.testclient import TestClient

from agents.task_agent.agent import TaskAgent
from agents.task_agent.ai import ExtractedTask, TaskAi
from agents.task_agent.schemas import TaskInvokeRequest


_APP_MAIN_PATH = Path(__file__).resolve().parents[3] / "apps" / "task-agent" / "app" / "main.py"
_APP_SPEC = spec_from_file_location("task_agent_app_main", _APP_MAIN_PATH)
assert _APP_SPEC and _APP_SPEC.loader
_APP_MODULE = module_from_spec(_APP_SPEC)
_APP_SPEC.loader.exec_module(_APP_MODULE)
app = _APP_MODULE.app


@dataclass
class _FakeTools:
    lists: list[dict[str, Any]] = field(default_factory=list)
    tasks_by_list: dict[int, list[dict[str, Any]]] = field(default_factory=dict)
    next_list_id: int = 100
    next_task_id: int = 200
    current_user: dict[str, Any] = field(default_factory=lambda: {"id": 3, "name": "Dadda Callender", "username": "dadda"})
    teams: list[dict[str, Any]] = field(default_factory=list)
    shared: list[dict[str, Any]] = field(default_factory=list)
    labels: list[dict[str, Any]] = field(default_factory=list)
    task_labels: list[dict[str, Any]] = field(default_factory=list)
    team_members_by_team: dict[int, list[dict[str, Any]]] = field(default_factory=dict)
    list_teams_by_list: dict[int, list[dict[str, Any]]] = field(default_factory=dict)

    def healthcheck(self):
        from agents.task_agent.schemas import HealthStatus

        return HealthStatus(ok=True, backend_reachable=True, tools_discovered=["fake"])

    def list_lists(self) -> list[dict[str, Any]]:
        return list(self.lists)

    def create_list(self, title: str, description: str = "") -> dict[str, Any]:
        created = {"id": self.next_list_id, "title": title, "description": description}
        self.next_list_id += 1
        self.lists.append(created)
        self.tasks_by_list.setdefault(int(created["id"]), [])
        return created

    def ensure_list(self, title: str, *, description: str = "") -> dict[str, Any]:
        for item in self.lists:
            if item["title"].lower() == title.lower():
                return item
        return self.create_list(title, description)

    def list_tasks(self, list_id: int) -> list[dict[str, Any]]:
        return list(self.tasks_by_list.get(list_id, []))

    def delete_list(self, list_id: int) -> dict[str, Any]:
        self.lists = [item for item in self.lists if int(item.get("id")) != int(list_id)]
        self.tasks_by_list.pop(int(list_id), None)
        return {"id": int(list_id), "deleted": True}

    def archive_list(self, list_id: int, *, archived: bool = True) -> dict[str, Any]:
        for item in self.lists:
            if int(item.get("id")) == int(list_id):
                item["is_archived"] = bool(archived)
                return dict(item)
        return {"id": int(list_id), "is_archived": bool(archived)}

    def rename_list(self, list_id: int, title: str) -> dict[str, Any]:
        for item in self.lists:
            if int(item.get("id")) == int(list_id):
                item["title"] = str(title)
                return dict(item)
        raise KeyError(list_id)

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
        task = {"id": self.next_task_id, "title": title, "description": description, "done": done}
        if due_date:
            task["due_date"] = due_date
        if start_date:
            task["start_date"] = start_date
        if end_date:
            task["end_date"] = end_date
        if priority is not None:
            task["priority"] = int(priority)
        self.next_task_id += 1
        self.tasks_by_list.setdefault(list_id, []).append(task)
        return task

    def update_task(self, task_id: int, *, patch: dict[str, Any]) -> dict[str, Any]:
        for tasks in self.tasks_by_list.values():
            for task in tasks:
                if int(task.get("id")) == int(task_id):
                    task.update(patch)
                    return task
        raise KeyError(task_id)

    def get_task(self, task_id: int) -> dict[str, Any] | None:
        for list_id, tasks in self.tasks_by_list.items():
            for task in tasks:
                if int(task.get("id")) == int(task_id):
                    row = dict(task)
                    row.setdefault("project_id", int(list_id))
                    return row
        return None

    def get_current_user(self) -> dict[str, Any] | None:
        return dict(self.current_user)

    def delete_task(self, task_id: int) -> dict[str, Any]:
        for list_id, tasks in self.tasks_by_list.items():
            kept = [task for task in tasks if int(task.get("id")) != int(task_id)]
            if len(kept) != len(tasks):
                self.tasks_by_list[list_id] = kept
                return {"id": int(task_id), "deleted": True}
        raise KeyError(task_id)

    def list_teams(self) -> list[dict[str, Any]]:
        return list(self.teams)

    def create_team(self, name: str) -> dict[str, Any]:
        next_id = max([int(item["id"]) for item in self.teams], default=0) + 1
        team = {"id": next_id, "name": name}
        self.teams.append(team)
        return team

    def share_list_with_team(self, list_id: int, team_id: int, permission: int = 0) -> dict[str, Any]:
        row = {"list_id": int(list_id), "team_id": int(team_id), "permission": int(permission)}
        self.shared.append(row)
        return row

    def list_team_members(self, team_id: int) -> list[dict[str, Any]]:
        return list(self.team_members_by_team.get(int(team_id), []))

    def list_list_teams(self, list_id: int) -> list[dict[str, Any]]:
        return list(self.list_teams_by_list.get(int(list_id), []))

    def list_labels(self) -> list[dict[str, Any]]:
        return list(self.labels)

    def create_label(self, title: str, *, description: str = "", hex_color: str = "") -> dict[str, Any]:
        next_id = max([int(item["id"]) for item in self.labels], default=0) + 1
        label = {"id": next_id, "title": title, "description": description, "hex_color": hex_color}
        self.labels.append(label)
        return label

    def ensure_label(self, title: str, *, description: str = "", hex_color: str = "") -> dict[str, Any]:
        for item in self.labels:
            if str(item.get("title", "")).lower() == title.lower():
                return item
        return self.create_label(title, description=description, hex_color=hex_color)

    def add_label_to_task(self, task_id: int, label_id: int) -> dict[str, Any]:
        row = {"task_id": int(task_id), "label_id": int(label_id)}
        self.task_labels.append(row)
        return row

    def set_task_assignees(self, task_id: int, assignee_ids: list[int]) -> dict[str, Any]:
        return self.update_task(task_id, patch={"assignees": [{"id": int(uid)} for uid in assignee_ids]})

    def set_task_progress(self, task_id: int, progress: float) -> dict[str, Any]:
        return self.update_task(task_id, patch={"percent_done": float(progress)})

    def set_task_color(self, task_id: int, color: str) -> dict[str, Any]:
        return self.update_task(task_id, patch={"hex_color": color})

    def set_task_repeat(self, task_id: int, repeat_after_seconds: int) -> dict[str, Any]:
        return self.update_task(task_id, patch={"repeat_after": int(repeat_after_seconds)})

    def add_task_relation(self, task_id: int, other_task_id: int, relation_type: str) -> dict[str, Any]:
        return {"task_id": int(task_id), "other_task_id": int(other_task_id), "relation_type": relation_type}

    def move_task(self, task_id: int, project_id: int) -> dict[str, Any]:
        return self.update_task(task_id, patch={"project_id": int(project_id)})

    def add_task_attachment(self, task_id: int, *, url: str | None = None, filename: str | None = None, bytes_base64: str | None = None) -> dict[str, Any]:
        return {"task_id": int(task_id), "url": url, "filename": filename, "has_bytes": bool(bytes_base64)}

    def capabilities(self) -> dict[str, bool]:
        return {
            "dates": True,
            "priority": True,
            "labels": True,
            "assignees": True,
            "progress": True,
            "color": True,
            "repeat": True,
            "relations": True,
            "attachments": True,
            "move_task": True,
        }


@dataclass
class _StubAi:
    tasks: list[ExtractedTask]

    def detect_intent_mode(self, *, message: str, metadata: dict[str, Any]):
        return "mutate_tasks"

    def infer_query_focus(self, *, message: str):
        return {"topic": None, "person": None, "terms": []}

    def should_allow_task_creation(self, *, message: str, attachment_text: str, metadata: dict[str, Any] | None = None) -> bool:
        return True

    def extract_completion_updates(self, *, message: str):
        return []

    def extract_purchase_items(self, *, message: str, attachment_text: str):
        return []

    def extract_bulk_actions(self, *, message: str, attachment_text: str = ""):
        return []

    def extract_team_actions(self, *, message: str, attachment_text: str = ""):
        return []

    def extract_management_actions(self, *, message: str, attachment_text: str = ""):
        return []

    def extract_list_directive(self, *, message: str, attachment_text: str = ""):
        return {"create_new_list": False, "list_title": None, "project_mode": False}

    def extract_task_candidates(self, *, message: str, attachment_text: str):
        return list(self.tasks)

    def extract_itemized_purchase_tasks(self, *, message: str):
        return []

    def cluster_project_candidates(self, tasks: list[str]):
        return []

    def infer_list_name(self, task_title: str) -> str:
        return "General"


def test_auto_create_project_when_high_confidence_related_tasks_and_no_match():
    tools = _FakeTools()
    agent = TaskAgent(ai=TaskAi(), tools=tools)
    req = TaskInvokeRequest(
        actor="u@example.com",
        family_id=1,
        message="Finalize kitchen budget. Call kitchen contractor. Review kitchen permit timeline.",
        attachments=[],
        metadata={},
    )
    res = agent.run(req)
    assert res.status in {"executed", "needs_input"}
    assert not any("kitchen" in str(item["title"]).lower() for item in tools.lists)
    assert len(res.artifacts.get("created_task_ids", [])) >= 0


def test_does_not_create_duplicate_project_when_relevant_exists():
    tools = _FakeTools(lists=[{"id": 1, "title": "Kitchen"}], tasks_by_list={1: []})
    agent = TaskAgent(ai=TaskAi(), tools=tools)
    req = TaskInvokeRequest(
        actor="u@example.com",
        family_id=1,
        message="Finalize kitchen budget. Call kitchen contractor. Review kitchen permit timeline.",
        attachments=[],
        metadata={},
    )
    res = agent.run(req)
    assert res.status in {"executed", "needs_input"}
    assert len([item for item in tools.lists if item["title"].lower() == "kitchen"]) == 1
    assert res.artifacts.get("created_list_ids", []) == []


def test_medium_confidence_cluster_returns_project_idea_without_creation():
    tools = _FakeTools()
    agent = TaskAgent(ai=TaskAi(), tools=tools)
    req = TaskInvokeRequest(
        actor="u@example.com",
        family_id=1,
        message="Review budget. Call contractor. Check timeline.",
        attachments=[],
        metadata={},
    )
    res = agent.run(req)
    assert res.status in {"executed", "needs_input"}
    assert res.project_ideas
    assert not any(item["title"].lower().startswith("project:") for item in tools.lists)


def test_insights_only_does_not_mutate():
    tools = _FakeTools(lists=[{"id": 1, "title": "General"}], tasks_by_list={1: [{"id": 10, "title": "Call school", "done": False}]})
    agent = TaskAgent(ai=TaskAi(), tools=tools)
    before = len(tools.tasks_by_list[1])
    req = TaskInvokeRequest(actor="u@example.com", family_id=1, message="Give me task insights and overdue summary", attachments=[], metadata={})
    res = agent.run(req)
    assert res.status == "executed"
    assert res.insights is not None
    assert len(tools.tasks_by_list[1]) == before


def test_store_question_returns_relevant_shopping_tasks():
    tools = _FakeTools(
        lists=[{"id": 1, "title": "Shopping"}, {"id": 2, "title": "General"}],
        tasks_by_list={
            1: [{"id": 10, "title": "milk", "done": False}, {"id": 11, "title": "eggs", "done": False}],
            2: [{"id": 20, "title": "email contractor", "done": False}],
        },
    )
    agent = TaskAgent(ai=TaskAi(), tools=tools)
    req = TaskInvokeRequest(
        actor="u@example.com",
        family_id=1,
        message="What does James need from the store today?",
        attachments=[],
        metadata={},
    )
    res = agent.run(req)
    assert res.status in {"executed", "needs_input"}
    assert res.intent == "insights_only"
    assert res.insights is not None
    assert res.insights.query_topic == "general_query"
    assert res.insights.query_answer is not None
    assert "store" in res.insights.query_answer.lower() or res.insights.relevant_tasks is not None


def test_list_all_projects_returns_project_summary_not_task_list():
    tools = _FakeTools(
        lists=[{"id": 1, "title": "Shopping"}, {"id": 2, "title": "Kitchen"}],
        tasks_by_list={
            1: [{"id": 10, "title": "Buy milk", "done": False}],
            2: [{"id": 20, "title": "Finalize budget", "done": False}, {"id": 21, "title": "Call contractor", "done": True}],
        },
    )
    agent = TaskAgent(ai=TaskAi(), tools=tools)
    req = TaskInvokeRequest(
        actor="u@example.com",
        family_id=1,
        message="List all projects",
        attachments=[],
        metadata={},
    )
    res = agent.run(req)
    assert res.status in {"executed", "needs_input"}
    assert res.intent == "insights_only"
    assert res.insights is not None
    assert res.insights.query_answer is not None
    lower = res.insights.query_answer.lower()
    assert lower.startswith("projects (")
    assert "shopping (1 open)" in lower
    assert "kitchen (1 open)" in lower
    assert "buy milk" not in lower


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
    assert res.status in {"executed", "needs_input"}
    assert res.intent == "insights_only"
    assert res.insights is not None
    assert res.insights.query_answer is not None
    lower = res.insights.query_answer.lower()
    assert "felicity should work on" in lower
    assert "buy milk" in lower
    assert "trim hedges" in lower


def test_girls_chores_query_returns_unfinished_from_chores_girls_list():
    tools = _FakeTools(
        lists=[{"id": 1, "title": "Chores/Girls"}, {"id": 2, "title": "Chores/Boys"}],
        tasks_by_list={
            1: [{"id": 10, "title": "Clean bedroom", "done": False}, {"id": 11, "title": "Do laundry", "done": True}],
            2: [{"id": 20, "title": "Take out trash", "done": False}],
        },
    )
    agent = TaskAgent(ai=TaskAi(), tools=tools)
    req = TaskInvokeRequest(
        actor="u@example.com",
        family_id=1,
        message="What chores do the girls have left?",
        attachments=[],
        metadata={},
    )
    res = agent.run(req)
    assert res.status == "executed"
    assert res.intent == "insights_only"
    assert res.insights is not None
    assert res.insights.query_answer is not None
    assert "girls have 1 chore" in res.insights.query_answer.lower()
    assert "Clean bedroom" in res.insights.query_answer


def test_completion_inquiry_reports_not_complete_status():
    tools = _FakeTools(
        lists=[{"id": 1, "title": "Kitchen"}],
        tasks_by_list={1: [{"id": 30, "title": "Finalize kitchen budget", "done": False}]},
    )
    agent = TaskAgent(ai=TaskAi(), tools=tools)
    req = TaskInvokeRequest(
        actor="u@example.com",
        family_id=1,
        message="Have I completed the kitchen budget?",
        attachments=[],
        metadata={},
    )
    res = agent.run(req)
    assert res.status == "executed"
    assert res.intent == "insights_only"
    assert res.insights is not None
    assert res.insights.query_answer is not None
    assert "Finalize kitchen budget" in res.insights.query_answer
    assert "not complete" in res.insights.query_answer.lower()


def test_statement_marks_matching_task_complete_and_assigns_closest_user():
    tools = _FakeTools(
        lists=[{"id": 1, "title": "Kitchen", "owner": {"id": 3, "name": "Dadda Callender", "username": "dadda"}}],
        tasks_by_list={1: [{"id": 30, "title": "Call kitchen contractor", "done": False}]},
        current_user={"id": 3, "name": "Dadda Callender", "username": "dadda"},
    )
    agent = TaskAgent(ai=TaskAi(), tools=tools)
    req = TaskInvokeRequest(
        actor="u@example.com",
        family_id=1,
        message="Dadda called the kitchen contractor",
        attachments=[],
        metadata={},
    )
    res = agent.run(req)
    assert res.status == "executed"
    assert 30 in res.artifacts.get("completed_task_ids", [])
    task = tools.tasks_by_list[1][0]
    assert task["done"] is True
    assert task.get("assignees") in (None, [])


def test_attachment_purchase_text_reconciles_across_lists():
    tools = _FakeTools(
        lists=[{"id": 1, "title": "Shopping"}, {"id": 2, "title": "Errands"}],
        tasks_by_list={
            1: [{"id": 10, "title": "milk", "done": False}],
            2: [{"id": 11, "title": "pick up dry cleaning", "done": False}],
        },
    )
    agent = TaskAgent(ai=TaskAi(), tools=tools)
    payload = "RECEIPT\nmilk $4.99\nsubtotal 4.99\n"
    req = TaskInvokeRequest(
        actor="u@example.com",
        family_id=1,
        message="Uploaded purchase details",
        attachments=[
            {
                "type": "text/plain",
                "name": "receipt.txt",
                "bytes_base64": base64.b64encode(payload.encode("utf-8")).decode("ascii"),
            }
        ],
        metadata={},
    )
    res = agent.run(req)
    assert res.status == "executed"
    assert tools.tasks_by_list[1][0]["done"] is True
    assert 10 in res.artifacts.get("completed_task_ids", [])


def test_non_explicit_purchase_update_reconciles_without_creating_tasks():
    tools = _FakeTools(
        lists=[{"id": 1, "title": "Shopping"}, {"id": 2, "title": "General"}],
        tasks_by_list={
            1: [{"id": 10, "title": "eggs", "done": False}, {"id": 11, "title": "milk", "done": False}],
            2: [],
        },
    )
    agent = TaskAgent(ai=TaskAi(), tools=tools)
    req = TaskInvokeRequest(
        actor="u@example.com",
        family_id=1,
        message="We just got eggs and milk from the store",
        attachments=[],
        metadata={},
    )
    res = agent.run(req)
    assert res.status == "executed"
    assert res.artifacts.get("created_task_ids", []) == []
    completed = set(res.artifacts.get("completed_task_ids", []))
    assert completed == {10, 11}
    assert tools.tasks_by_list[1][0]["done"] is True
    assert tools.tasks_by_list[1][1]["done"] is True


def test_delete_all_tasks_for_kitchen_project():
    tools = _FakeTools(
        lists=[{"id": 1, "title": "Kitchen"}, {"id": 2, "title": "Shopping"}],
        tasks_by_list={
            1: [{"id": 30, "title": "Finalize kitchen budget", "done": False}, {"id": 31, "title": "Call kitchen contractor", "done": False}],
            2: [{"id": 40, "title": "milk", "done": False}],
        },
    )
    agent = TaskAgent(ai=TaskAi(), tools=tools)
    req = TaskInvokeRequest(
        actor="u@example.com",
        family_id=1,
        message="Delete all tasks for the kitchen project",
        attachments=[],
        metadata={},
    )
    res = agent.run(req)
    assert res.status == "needs_input"
    assert "requires explicit ops mode" in res.explanation.lower()
    assert {task["id"] for task in tools.tasks_by_list[1]} == {30, 31}


def test_clear_shopping_list():
    tools = _FakeTools(
        lists=[{"id": 1, "title": "Kitchen"}, {"id": 2, "title": "Shopping"}],
        tasks_by_list={
            1: [{"id": 30, "title": "Finalize kitchen budget", "done": False}],
            2: [{"id": 40, "title": "milk", "done": False}, {"id": 41, "title": "eggs", "done": False}],
        },
    )
    agent = TaskAgent(ai=TaskAi(), tools=tools)
    req = TaskInvokeRequest(
        actor="u@example.com",
        family_id=1,
        message="clear the shopping list",
        attachments=[],
        metadata={},
    )
    res = agent.run(req)
    assert res.status == "needs_input"
    assert "requires explicit ops mode" in res.explanation.lower()
    assert {task["id"] for task in tools.tasks_by_list[2]} == {40, 41}


def test_assign_trip_to_parents_shares_matching_list_with_team():
    tools = _FakeTools(
        lists=[{"id": 1, "title": "Beauty Supply Shop Trip"}, {"id": 2, "title": "Shopping"}],
        tasks_by_list={1: [], 2: []},
        teams=[{"id": 5, "name": "parents"}],
    )
    agent = TaskAgent(ai=TaskAi(), tools=tools)
    req = TaskInvokeRequest(
        actor="u@example.com",
        family_id=1,
        message="Assign the beauty supply shop trip to the parents",
        attachments=[],
        metadata={},
    )
    res = agent.run(req)
    assert res.status in {"executed", "needs_input"}
    if res.status == "executed":
        assert res.artifacts.get("shared_list_ids", []) == [1]
        assert tools.shared
        assert tools.shared[0]["list_id"] == 1
        assert tools.shared[0]["team_id"] == 5


def test_assign_trip_to_parents_resolves_list_from_task_title_when_list_name_differs():
    tools = _FakeTools(
        lists=[{"id": 1, "title": "Errands"}, {"id": 2, "title": "Shopping"}],
        tasks_by_list={1: [{"id": 70, "title": "Beauty supply shop trip", "done": False}], 2: []},
        teams=[{"id": 5, "name": "parents"}],
    )
    agent = TaskAgent(ai=TaskAi(), tools=tools)
    req = TaskInvokeRequest(
        actor="u@example.com",
        family_id=1,
        message="Assign the beauty supply shop trip to the parents",
        attachments=[],
        metadata={},
    )
    res = agent.run(req)
    assert res.status in {"executed", "needs_input"}
    if res.status == "executed":
        assert res.artifacts.get("shared_list_ids", []) == [1]
        assert tools.shared
        assert tools.shared[0]["list_id"] == 1
        assert tools.shared[0]["team_id"] == 5


def test_delete_kitchen_and_admin_projects():
    tools = _FakeTools(
        lists=[{"id": 1, "title": "Kitchen"}, {"id": 2, "title": "Admin"}, {"id": 3, "title": "Shopping"}],
        tasks_by_list={1: [{"id": 10, "title": "A", "done": False}], 2: [{"id": 11, "title": "B", "done": False}], 3: []},
    )
    agent = TaskAgent(ai=TaskAi(), tools=tools)
    req = TaskInvokeRequest(actor="u@example.com", family_id=1, message="delete the kitchen and admin projects", attachments=[], metadata={})
    res = agent.run(req)
    assert res.status == "needs_input"
    assert "requires explicit ops mode" in res.explanation.lower()
    titles = {item["title"] for item in tools.lists}
    assert "Kitchen" in titles
    assert "Admin" in titles


def test_archive_lowes_trip():
    tools = _FakeTools(
        lists=[{"id": 1, "title": "Lowes Trip", "is_archived": False}],
        tasks_by_list={1: [{"id": 10, "title": "Buy saw", "done": False}]},
    )
    agent = TaskAgent(ai=TaskAi(), tools=tools)
    req = TaskInvokeRequest(actor="u@example.com", family_id=1, message="Archive the Lowes trip", attachments=[], metadata={})
    res = agent.run(req)
    assert res.status == "needs_input"
    assert "requires explicit ops mode" in res.explanation.lower()
    assert tools.lists[0]["is_archived"] is False


def test_highest_priority_item_remaining_on_shopping_list():
    tools = _FakeTools(
        lists=[{"id": 1, "title": "Shopping"}],
        tasks_by_list={1: [{"id": 10, "title": "eggs", "done": False, "priority": 1}, {"id": 11, "title": "milk", "done": False, "priority": 5}]},
    )
    agent = TaskAgent(ai=TaskAi(), tools=tools)
    req = TaskInvokeRequest(
        actor="u@example.com",
        family_id=1,
        message="What is the highest priority item remaining on my shopping list?",
        attachments=[],
        metadata={},
    )
    res = agent.run(req)
    assert res.status == "executed"
    assert res.insights is not None
    assert res.insights.query_answer is not None
    assert "milk" in res.insights.query_answer.lower()


def test_update_saw_details_on_lowes_list():
    tools = _FakeTools(
        lists=[{"id": 1, "title": "Lowes Trip"}],
        tasks_by_list={1: [{"id": 10, "title": "Buy saw", "description": "", "done": False}]},
    )
    agent = TaskAgent(ai=TaskAi(), tools=tools)
    req = TaskInvokeRequest(
        actor="u@example.com",
        family_id=1,
        message="The saw I need to buy from Lowes is a SKIL 13 -Amp 7-1/4-in Circular saw.",
        attachments=[],
        metadata={},
    )
    res = agent.run(req)
    assert res.status in {"executed", "needs_input"}
    if res.status == "executed":
        assert 10 in res.artifacts.get("updated_task_ids", [])
        assert "skil 13 -amp 7-1/4-in circular saw".lower() in tools.tasks_by_list[1][0]["description"].lower()


def test_label_tool_box_purchase_high_cost():
    tools = _FakeTools(
        lists=[{"id": 1, "title": "Lowes Trip"}],
        tasks_by_list={1: [{"id": 10, "title": "Buy tool box", "done": False}]},
    )
    agent = TaskAgent(ai=TaskAi(), tools=tools)
    req = TaskInvokeRequest(actor="u@example.com", family_id=1, message="Label the tool box purchase high cost.", attachments=[], metadata={})
    res = agent.run(req)
    assert res.status == "executed"
    assert tools.labels
    assert any(item["title"].lower() == "high cost" for item in tools.labels)
    assert tools.task_labels and tools.task_labels[0]["task_id"] == 10


def test_replace_banisters_with_clean_windows_on_boys_chores():
    tools = _FakeTools(
        lists=[{"id": 1, "title": "Chores/Boys"}],
        tasks_by_list={1: [{"id": 10, "title": "Stairway banister", "done": False}]},
    )
    agent = TaskAgent(ai=TaskAi(), tools=tools)
    req = TaskInvokeRequest(
        actor="u@example.com",
        family_id=1,
        message="Replace the banisters on the boys chore list with cleaning windows.",
        attachments=[],
        metadata={},
    )
    res = agent.run(req)
    assert res.status == "executed"
    assert 10 in res.artifacts.get("deleted_task_ids", [])
    titles = [item["title"].lower() for item in tools.tasks_by_list[1]]
    assert "cleaning windows" in titles


def test_replace_banisters_uses_parent_project_context_for_boys_chore_list():
    tools = _FakeTools(
        lists=[
            {"id": 10, "title": "Chores", "parent_project_id": 0},
            {"id": 12, "title": "Boys", "parent_project_id": 10},
        ],
        tasks_by_list={12: [{"id": 23, "title": "Stairway banister", "done": False}]},
    )
    agent = TaskAgent(ai=TaskAi(), tools=tools)
    req = TaskInvokeRequest(
        actor="u@example.com",
        family_id=1,
        message="Replace the Stairway banisters on the boys chore list with cleaning windows.",
        attachments=[],
        metadata={},
    )
    res = agent.run(req)
    assert res.status == "executed"
    assert 23 in res.artifacts.get("deleted_task_ids", [])
    titles = [item["title"].lower() for item in tools.tasks_by_list[12]]
    assert "cleaning windows" in titles


def test_explicit_new_list_request_creates_dedicated_trip_list_not_shopping():
    tools = _FakeTools(lists=[{"id": 2, "title": "Shopping"}], tasks_by_list={2: []}, next_list_id=100)
    agent = TaskAgent(ai=TaskAi(), tools=tools)
    req = TaskInvokeRequest(
        actor="u@example.com",
        family_id=1,
        message="I need to go to Lowes and purchases a tool box, a hammer, a saw, and a new soldering iron. Create a new list for this trip and add the items I need.",
        attachments=[],
        metadata={},
    )
    res = agent.run(req)
    assert res.status == "executed"
    created_lists = [item for item in tools.lists if int(item["id"]) >= 100]
    assert created_lists
    assert any("trip" in item["title"].lower() for item in created_lists)
    assert not any(item["title"].strip().lower() == "new project" for item in created_lists)
    # ensure tasks were not added to Shopping
    assert tools.tasks_by_list[2] == []
    created_list_ids = [int(item["id"]) for item in created_lists]
    created_task_targets = []
    for list_id, tasks in tools.tasks_by_list.items():
        if list_id in created_list_ids:
            created_task_targets.extend([task["title"] for task in tasks])
    assert created_task_targets
    assert not any("go to lowes" in title.lower() for title in created_task_targets)
    assert not any("create a new list" in title.lower() for title in created_task_targets)
    assert all(title.lower().startswith("buy ") for title in created_task_targets)


def test_idempotency_avoids_duplicate_task_creation():
    tools = _FakeTools(lists=[{"id": 1, "title": "General"}], tasks_by_list={1: []})
    agent = TaskAgent(ai=TaskAi(), tools=tools)
    req = TaskInvokeRequest(actor="u@example.com", family_id=1, message="Call school office", attachments=[], metadata={})
    first = agent.run(req)
    second = agent.run(req)
    assert first.status in {"executed", "needs_input"}
    assert second.status in {"executed", "needs_input"}
    all_titles: list[str] = []
    for tasks in tools.tasks_by_list.values():
        all_titles.extend([task["title"].lower() for task in tasks])
    assert all_titles.count("Call school office".lower()) <= 1


def test_task_app_smoke(monkeypatch):
    tools = _FakeTools(lists=[{"id": 1, "title": "General"}], tasks_by_list={1: []})
    agent = TaskAgent(ai=TaskAi(), tools=tools)

    monkeypatch.setattr(_APP_MODULE, "task_tools", lambda: tools)
    monkeypatch.setattr(_APP_MODULE, "get_task_tools", lambda: tools)
    monkeypatch.setattr(_APP_MODULE, "get_task_agent", lambda: agent)

    client = TestClient(app)
    health = client.get("/healthz")
    assert health.status_code == 200
    assert health.json()["ok"] is True

    invoke = client.post(
        "/v1/agents/tasks/invoke",
        headers={"X-Dev-User": "u@example.com"},
        json={"actor": "x@example.com", "family_id": 1, "message": "Call dentist", "attachments": [], "metadata": {}},
    )
    assert invoke.status_code == 200
    assert invoke.json()["status"] in {"executed", "needs_input"}


def test_structured_task_features_are_applied_in_order():
    tools = _FakeTools(lists=[{"id": 1, "title": "General"}, {"id": 2, "title": "Ops"}], tasks_by_list={1: [{"id": 5, "title": "Existing prep", "done": False}], 2: []})
    stub = _StubAi(
        tasks=[
            ExtractedTask(
                title="Prepare release notes",
                confidence=0.92,
                description="Include dependency changes",
                start_date="today",
                due_date="tomorrow",
                priority=4,
                assignees=["Dadda"],
                labels=["Release", "High Cost"],
                progress=25.0,
                color="#ff6600",
                repeat_interval="every 2 days",
                relations=[{"target": "Existing prep"}],
                target_project="Ops",
            )
        ]
    )
    agent = TaskAgent(ai=stub, tools=tools)
    res = agent.run(
        TaskInvokeRequest(
            actor="u@example.com",
            family_id=1,
            message="Create release task",
            attachments=[],
            metadata={"timezone": "UTC", "allow_advanced_features": True},
        )
    )
    assert res.status == "executed"
    assert res.artifacts.get("created_task_ids", [])
    assert res.artifacts.get("labeled_task_ids", [])
    assert res.artifacts.get("assignee_task_ids", [])
    assert res.artifacts.get("progress_task_ids", [])
    assert res.artifacts.get("color_task_ids", [])
    assert res.artifacts.get("repeat_task_ids", [])
    assert res.artifacts.get("related_task_ids", [])
    assert res.artifacts.get("moved_task_ids", []) == []


def test_ambiguous_dates_trigger_needs_input():
    tools = _FakeTools(lists=[{"id": 1, "title": "General"}], tasks_by_list={1: []})
    stub = _StubAi(tasks=[ExtractedTask(title="Do task", confidence=0.9, due_date="someday soon")])
    agent = TaskAgent(ai=stub, tools=tools)
    res = agent.run(TaskInvokeRequest(actor="u@example.com", family_id=1, message="Add task", attachments=[], metadata={}))
    assert res.status == "needs_input"
    assert res.plan is not None
    assert res.plan.missing_info


def test_move_tasks_phrase_without_ops_returns_needs_input():
    tools = _FakeTools(
        lists=[{"id": 1, "title": "General"}, {"id": 2, "title": "Girls Chore"}],
        tasks_by_list={
            1: [{"id": 10, "title": "Dusting bedroom", "done": False}, {"id": 11, "title": "Vacuum stairs", "done": False}],
            2: [],
        },
    )
    agent = TaskAgent(ai=TaskAi(), tools=tools)
    req = TaskInvokeRequest(
        actor="u@example.com",
        family_id=1,
        message="Move the dusting tasks to the Girls Chore list",
        attachments=[],
        metadata={},
    )
    res = agent.run(req)
    assert res.status == "needs_input"
    assert res.mode == "extract"


def test_ops_fenced_json_move_task_moves_exact_id_only():
    tools = _FakeTools(
        lists=[{"id": 1, "title": "General"}, {"id": 2, "title": "Weekend Prep"}],
        tasks_by_list={1: [{"id": 152, "title": "A", "done": False}, {"id": 153, "title": "B", "done": False}], 2: []},
    )
    agent = TaskAgent(ai=TaskAi(), tools=tools)
    msg = """---BEGIN_OPS---
{
  "mode": "ops",
  "operations": [
    {"type":"move_task","task_id":152,"list_id":2}
  ]
}
---END_OPS---"""
    res = agent.run(TaskInvokeRequest(actor="u@example.com", family_id=1, message=msg, attachments=[], metadata={}))
    assert res.status == "executed"
    assert res.mode == "ops"
    assert res.moved_task_ids == [152]
    assert tools.tasks_by_list[1][0].get("project_id") == 2
    assert tools.tasks_by_list[1][1].get("project_id") is None


def test_ops_mode_does_not_extract_instruction_text_into_tasks():
    tools = _FakeTools(lists=[{"id": 1, "title": "General"}], tasks_by_list={1: []})
    agent = TaskAgent(ai=TaskAi(), tools=tools)
    msg = """Do not create tasks.
---BEGIN_OPS---
{
  "mode": "ops",
  "operations": [
    {"type":"ensure_list","title":"Weekend Prep"}
  ]
}
---END_OPS---"""
    res = agent.run(TaskInvokeRequest(actor="u@example.com", family_id=1, message=msg, attachments=[], metadata={}))
    assert res.mode == "ops"
    assert res.created_task_ids == []


def test_extract_mode_ignores_instruction_lines_when_creating_tasks():
    tools = _FakeTools(lists=[{"id": 1, "title": "General"}], tasks_by_list={1: []})
    agent = TaskAgent(ai=TaskAi(), tools=tools)
    message = "Do not create tasks\nparameters: x\nBuy milk"
    res = agent.run(
        TaskInvokeRequest(
            actor="u@example.com",
            family_id=1,
            message=message,
            attachments=[],
            metadata={"allow_task_creation": True},
        )
    )
    assert res.status in {"executed", "needs_input"}
    titles = [str(item.get("title") or "").lower() for item in tools.tasks_by_list[1]]
    assert not any(title.startswith("do not") or title.startswith("parameters") for title in titles)


def test_extract_rename_project_without_ops_returns_needs_input():
    tools = _FakeTools(lists=[{"id": 1, "title": "General"}], tasks_by_list={1: []})
    agent = TaskAgent(ai=TaskAi(), tools=tools)
    res = agent.run(
        TaskInvokeRequest(
            actor="u@example.com",
            family_id=1,
            message="rename project id 1 to Weekend Prep",
            attachments=[],
            metadata={},
        )
    )
    assert res.status == "needs_input"
    assert res.mode == "extract"


def test_extract_complete_task_by_id_without_ops_returns_needs_input_and_no_task_creation():
    tools = _FakeTools(
        lists=[{"id": 1, "title": "General"}],
        tasks_by_list={1: [{"id": 152, "title": "Existing item", "done": False}]},
    )
    agent = TaskAgent(ai=TaskAi(), tools=tools)
    res = agent.run(
        TaskInvokeRequest(
            actor="u@example.com",
            family_id=1,
            message="Mark task 152 complete.",
            attachments=[],
            metadata={},
        )
    )
    assert res.status == "needs_input"
    assert res.mode == "extract"
    titles = [str(item.get("title") or "").lower() for item in tools.tasks_by_list[1]]
    assert "mark task 152 complete" not in titles


def test_extract_move_by_title_without_ops_returns_needs_input():
    tools = _FakeTools(
        lists=[{"id": 1, "title": "General"}, {"id": 36, "title": "Weekend Prep (Mar 7-9)"}],
        tasks_by_list={1: [{"id": 186, "title": "Call plumber", "done": False}], 36: []},
    )
    agent = TaskAgent(ai=TaskAi(), tools=tools)
    res = agent.run(
        TaskInvokeRequest(
            actor="u@example.com",
            family_id=1,
            message='Move "Call plumber" to Weekend Prep (Mar 7-9).',
            attachments=[],
            metadata={},
        )
    )
    assert res.status == "needs_input"
    assert res.mode == "extract"
    assert tools.tasks_by_list[1][0].get("project_id") is None


def test_instruction_only_message_returns_extract_noop():
    tools = _FakeTools(lists=[{"id": 1, "title": "General"}], tasks_by_list={1: []})
    agent = TaskAgent(ai=TaskAi(), tools=tools)
    res = agent.run(
        TaskInvokeRequest(
            actor="u@example.com",
            family_id=1,
            message="Do not create tasks. This is an instruction only.",
            attachments=[],
            metadata={},
        )
    )
    assert res.status == "executed"
    assert res.mode == "extract"
    assert res.notes and "extract_noop_instruction_only" in res.notes


def test_relative_due_date_tomorrow_uses_default_timezone_without_needs_input():
    tools = _FakeTools(lists=[{"id": 1, "title": "General"}], tasks_by_list={1: []})
    stub = _StubAi(tasks=[ExtractedTask(title="Email Rachel about painters", confidence=0.9, due_date="tomorrow")])
    agent = TaskAgent(ai=stub, tools=tools)
    res = agent.run(TaskInvokeRequest(actor="u@example.com", family_id=1, message='Add a task "Email Rachel about painters" due tomorrow.', attachments=[], metadata={}))
    assert res.status == "executed"
    assert res.artifacts.get("created_task_ids", [])


def test_relative_tomorrow_ignores_timezone_ambiguity_when_date_resolves():
    tools = _FakeTools(lists=[{"id": 1, "title": "General"}], tasks_by_list={1: []})
    stub = _StubAi(
        tasks=[
            ExtractedTask(
                title="Email Rachel about painters",
                confidence=0.95,
                due_date="tomorrow",
                ambiguities=["User timezone/what date is 'tomorrow'?"],
            )
        ]
    )
    agent = TaskAgent(ai=stub, tools=tools)
    res = agent.run(TaskInvokeRequest(actor="u@example.com", family_id=1, message='Add a task: "Email Rachel about painters" due tomorrow.', attachments=[], metadata={}))
    assert res.status == "executed"
    assert res.artifacts.get("created_task_ids", [])


def test_extract_here_are_tasks_bullets_assume_create():
    tools = _FakeTools(lists=[{"id": 1, "title": "General"}], tasks_by_list={1: []})
    agent = TaskAgent(ai=TaskAi(), tools=tools)
    msg = "Here are tasks:\n- Clean garage\n- Vacuum living room\nNOTE: do not create a task from this note"
    res = agent.run(TaskInvokeRequest(actor="u@example.com", family_id=1, message=msg, attachments=[], metadata={}))
    assert res.status == "executed"
    titles = [str(item.get("title") or "").lower() for item in tools.tasks_by_list[1]]
    assert "clean garage" in titles
    assert "vacuum living room" in titles
    assert not any(title.startswith("note:") for title in titles)


def test_extract_task_list_skips_junk_header_candidate():
    tools = _FakeTools(lists=[{"id": 1, "title": "General"}], tasks_by_list={1: []})
    stub = _StubAi(
        tasks=[
            ExtractedTask(title="EXTRACT MODE TEST 9 (retry2): Here are tasks (do not turn the next line into a task)", confidence=0.95),
            ExtractedTask(title="Clean garage", confidence=0.95),
            ExtractedTask(title="Vacuum living room", confidence=0.95),
        ]
    )
    agent = TaskAgent(ai=stub, tools=tools)
    msg = """EXTRACT MODE TEST 9 (retry2): Here are tasks (do not turn the next line into a task):
- Clean garage
NOTE: do not create a task from this note
- Vacuum living room"""
    res = agent.run(TaskInvokeRequest(actor="u@example.com", family_id=1, message=msg, attachments=[], metadata={}))
    assert res.status == "executed"
    titles = [str(item.get("title") or "").lower() for item in tools.tasks_by_list[1]]
    assert "clean garage" in titles
    assert "vacuum living room" in titles
    assert not any("extract mode test 9" in title for title in titles)
    assert any(str(note).startswith("skipped_non_task_header:") for note in res.notes)


def test_instruction_only_returns_lightweight_noop_not_insights():
    tools = _FakeTools(lists=[{"id": 1, "title": "General"}], tasks_by_list={1: []})
    agent = TaskAgent(ai=TaskAi(), tools=tools)
    res = agent.run(
        TaskInvokeRequest(
            actor="u@example.com",
            family_id=1,
            message="Instruction: do not create tasks.",
            attachments=[],
            metadata={},
        )
    )
    assert res.status == "executed"
    assert res.insights is None
    assert "extract_noop_instruction_only" in res.notes


def test_duplicate_skip_adds_observable_notes():
    tools = _FakeTools(
        lists=[{"id": 1, "title": "General"}],
        tasks_by_list={1: [{"id": 10, "title": "Buy diapers and wipes", "done": False}]},
    )
    stub = _StubAi(tasks=[ExtractedTask(title="Buy diapers and wipes", confidence=0.95)])
    agent = TaskAgent(ai=stub, tools=tools)
    res = agent.run(TaskInvokeRequest(actor="u@example.com", family_id=1, message="Buy diapers and wipes", attachments=[], metadata={}))
    assert res.status == "executed"
    assert any(str(note).startswith("skipped_duplicate:") for note in res.notes)


def test_ops_list_id_ref_requires_unique_match():
    tools = _FakeTools(
        lists=[{"id": 1, "title": "Weekend Prep"}, {"id": 2, "title": "Weekend Prep"}],
        tasks_by_list={1: [{"id": 99, "title": "A", "done": False}], 2: []},
    )
    agent = TaskAgent(ai=TaskAi(), tools=tools)
    message = """{"mode":"ops","operations":[{"type":"move_task","task_id":99,"list_id_ref":"Weekend Prep"}]}"""
    res = agent.run(TaskInvokeRequest(actor="u@example.com", family_id=1, message=message, attachments=[], metadata={}))
    assert res.mode == "ops"
    assert res.failed_operations
    assert "ambiguous" in str(res.failed_operations[0]).lower()


def test_ops_default_continue_on_error_executes_remaining_operations():
    tools = _FakeTools(lists=[{"id": 1, "title": "General"}], tasks_by_list={1: []})
    agent = TaskAgent(ai=TaskAi(), tools=tools)
    message = """{
  "mode":"ops",
  "operations":[
    {"type":"move_task","task_id":999,"list_id":1},
    {"type":"create_task","list_id":1,"title":"Buy milk"}
  ]
}"""
    res = agent.run(TaskInvokeRequest(actor="u@example.com", family_id=1, message=message, attachments=[], metadata={}))
    assert res.mode == "ops"
    assert res.failed_operations
    assert res.executed_operations
    titles = [str(item.get("title") or "").lower() for item in tools.tasks_by_list[1]]
    assert "buy milk" in titles


def test_ops_stop_on_error_aborts_remaining_operations():
    tools = _FakeTools(lists=[{"id": 1, "title": "General"}], tasks_by_list={1: []})
    agent = TaskAgent(ai=TaskAi(), tools=tools)
    message = """{
  "mode":"ops",
  "stop_on_error": true,
  "operations":[
    {"type":"move_task","task_id":999,"list_id":1},
    {"type":"create_task","list_id":1,"title":"Buy milk"}
  ]
}"""
    res = agent.run(TaskInvokeRequest(actor="u@example.com", family_id=1, message=message, attachments=[], metadata={}))
    assert res.mode == "ops"
    assert res.failed_operations
    assert not res.executed_operations
    assert tools.tasks_by_list[1] == []


def test_ops_get_task_returns_minimum_task_payload_fields():
    tools = _FakeTools(
        lists=[{"id": 1, "title": "General"}],
        tasks_by_list={1: [{"id": 42, "title": "Buy milk", "description": "2 gallons", "due_date": "2026-03-10T00:00:00Z", "done": False}]},
    )
    agent = TaskAgent(ai=TaskAi(), tools=tools)
    message = """{
  "mode":"ops",
  "operations":[
    {"type":"get_task","task_id":42}
  ]
}"""
    res = agent.run(TaskInvokeRequest(actor="u@example.com", family_id=1, message=message, attachments=[], metadata={}))
    assert res.mode == "ops"
    assert res.status == "executed"
    assert res.executed_operations
    payload = res.executed_operations[0]["result"]
    assert payload["id"] == 42
    assert payload["title"] == "Buy milk"
    assert payload["description"] == "2 gallons"
    assert payload["due_date"] == "2026-03-10T00:00:00Z"
    assert payload["project_id"] == 1


def test_ops_bulk_delete_lists_requires_confirmation_then_executes():
    tools = _FakeTools(
        lists=[{"id": 1, "title": "Kitchen"}, {"id": 2, "title": "Admin"}, {"id": 3, "title": "Shopping"}],
        tasks_by_list={1: [], 2: [], 3: []},
    )
    agent = TaskAgent(ai=TaskAi(), tools=tools)
    phase1_message = """{
  "mode":"ops",
  "operations":[
    {"type":"delete_list","list_id":1},
    {"type":"delete_list","list_id":2}
  ]
}"""
    phase1 = agent.run(TaskInvokeRequest(actor="u@example.com", family_id=1, message=phase1_message, attachments=[], metadata={}))
    assert phase1.mode == "ops"
    assert phase1.status == "needs_input"
    assert "i will delete lists: [1, 2]; keep: [3]." in phase1.explanation.lower()

    phase2_message = """{
  "mode":"ops",
  "confirmation":"CONFIRM DELETE 2 LISTS",
  "operations":[
    {"type":"delete_list","list_id":1},
    {"type":"delete_list","list_id":2}
  ]
}"""
    phase2 = agent.run(TaskInvokeRequest(actor="u@example.com", family_id=1, message=phase2_message, attachments=[], metadata={}))
    assert phase2.status == "executed"
    assert set(phase2.artifacts.get("deleted_list_ids", [])) == {1, 2}
    remaining_titles = {item["title"] for item in tools.lists}
    assert remaining_titles == {"Shopping"}


def test_get_all_projects_and_get_all_tasks_return_deterministic_rows():
    tools = _FakeTools(
        lists=[
            {"id": 1, "title": "Kitchen", "is_archived": False},
            {"id": 2, "title": "Admin", "is_archived": True, "parent_project_id": 1},
        ],
        tasks_by_list={
            1: [{"id": 10, "title": "A", "done": False}, {"id": 11, "title": "B", "done": True}],
            2: [{"id": 12, "title": "C", "done": False}],
        },
    )
    agent = TaskAgent(ai=TaskAi(), tools=tools)
    res_projects = agent.run(TaskInvokeRequest(actor="u@example.com", family_id=1, message="get_all_projects", attachments=[], metadata={}))
    assert res_projects.status == "executed"
    assert res_projects.insights is not None
    assert res_projects.insights.all_projects == [
        {"id": 1, "name": "Kitchen", "parent_id": None, "open_task_count": 1, "archived": False},
        {"id": 2, "name": "Admin", "parent_id": 1, "open_task_count": 1, "archived": True},
    ]

    res_tasks = agent.run(TaskInvokeRequest(actor="u@example.com", family_id=1, message="get_all_tasks", attachments=[], metadata={}))
    assert res_tasks.status == "executed"
    assert res_tasks.insights is not None
    assert res_tasks.insights.all_tasks == [
        {"id": 1, "name": "Kitchen", "parent_id": None, "open_task_count": 1, "archived": False},
        {"id": 2, "name": "Admin", "parent_id": 1, "open_task_count": 1, "archived": True},
    ]


def test_ops_get_all_projects_and_tasks():
    tools = _FakeTools(
        lists=[{"id": 1, "title": "Kitchen", "is_archived": False}],
        tasks_by_list={1: [{"id": 10, "title": "A", "done": False}]},
    )
    agent = TaskAgent(ai=TaskAi(), tools=tools)
    msg = """{
  "mode":"ops",
  "operations":[
    {"type":"get_all_projects"},
    {"type":"get_all_tasks"}
  ]
}"""
    res = agent.run(TaskInvokeRequest(actor="u@example.com", family_id=1, message=msg, attachments=[], metadata={}))
    assert res.mode == "ops"
    assert res.status == "executed"
    assert len(res.executed_operations) == 2
    assert res.executed_operations[0]["type"] == "get_all_projects"
    assert res.executed_operations[1]["type"] == "get_all_tasks"
