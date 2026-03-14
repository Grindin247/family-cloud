from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from agents.task_agent.schemas import HealthStatus
from agents.task_agent.tools import FallbackTaskTools, McpTaskTools, RestTaskTools, task_tools


@dataclass
class _FakeMcpClient:
    tools: list[str]
    responses: dict[str, Any]
    fail_calls: bool = False

    def discover_tools(self, *, timeout_seconds: float | None = None) -> list[str]:
        return list(self.tools)

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        if self.fail_calls:
            raise RuntimeError("mcp down")
        payload = self.responses.get(name, {})
        return payload if isinstance(payload, dict) else {"data": payload}


@dataclass
class _FakeRest:
    calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]]

    def _record(self, name: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append((name, args, kwargs))
        return {"id": 1, "ok": True}

    def healthcheck(self) -> HealthStatus:
        return HealthStatus(ok=True, backend_reachable=True, tools_discovered=["http.projects"])

    def list_lists(self) -> list[dict[str, Any]]:
        self.calls.append(("list_lists", (), {}))
        return [{"id": 1, "title": "Fallback"}]

    def create_list(self, title: str, description: str = "") -> dict[str, Any]:
        return self._record("create_list", title, description)

    def get_list(self, list_id: int) -> dict[str, Any] | None:
        self.calls.append(("get_list", (list_id,), {}))
        return {"id": list_id, "title": "Fallback"}

    def list_tasks(self, list_id: int) -> list[dict[str, Any]]:
        self.calls.append(("list_tasks", (list_id,), {}))
        return []

    def delete_list(self, list_id: int) -> dict[str, Any]:
        return self._record("delete_list", list_id)

    def archive_list(self, list_id: int, *, archived: bool = True) -> dict[str, Any]:
        return self._record("archive_list", list_id, archived=archived)

    def rename_list(self, list_id: int, title: str) -> dict[str, Any]:
        return self._record("rename_list", list_id, title=title)

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
        return self._record(
            "create_task",
            list_id,
            title=title,
            description=description,
            done=done,
            due_date=due_date,
            start_date=start_date,
            end_date=end_date,
            priority=priority,
        )

    def update_task(self, task_id: int, *, patch: dict[str, Any]) -> dict[str, Any]:
        return self._record("update_task", task_id, patch=patch)

    def get_task(self, task_id: int) -> dict[str, Any] | None:
        self.calls.append(("get_task", (task_id,), {}))
        return {"id": int(task_id), "title": "Task", "description": "", "project_id": 1}

    def delete_task(self, task_id: int) -> dict[str, Any]:
        return self._record("delete_task", task_id)

    def ensure_list(self, title: str, *, description: str = "") -> dict[str, Any]:
        return self._record("ensure_list", title, description=description)

    def get_current_user(self) -> dict[str, Any] | None:
        self.calls.append(("get_current_user", (), {}))
        return {"id": 7}

    def list_teams(self) -> list[dict[str, Any]]:
        self.calls.append(("list_teams", (), {}))
        return []

    def create_team(self, name: str) -> dict[str, Any]:
        return self._record("create_team", name)

    def share_list_with_team(self, list_id: int, team_id: int, permission: int = 0) -> dict[str, Any]:
        return self._record("share_list_with_team", list_id, team_id, permission=permission)

    def list_labels(self) -> list[dict[str, Any]]:
        self.calls.append(("list_labels", (), {}))
        return []

    def create_label(self, title: str, *, description: str = "", hex_color: str = "") -> dict[str, Any]:
        return self._record("create_label", title, description=description, hex_color=hex_color)

    def ensure_label(self, title: str, *, description: str = "", hex_color: str = "") -> dict[str, Any]:
        return self._record("ensure_label", title, description=description, hex_color=hex_color)

    def add_label_to_task(self, task_id: int, label_id: int) -> dict[str, Any]:
        return self._record("add_label_to_task", task_id, label_id)

    def set_task_assignees(self, task_id: int, assignee_ids: list[int]) -> dict[str, Any]:
        return self._record("set_task_assignees", task_id, assignee_ids=assignee_ids)

    def set_task_progress(self, task_id: int, progress: float) -> dict[str, Any]:
        return self._record("set_task_progress", task_id, progress=progress)

    def set_task_color(self, task_id: int, color: str) -> dict[str, Any]:
        return self._record("set_task_color", task_id, color=color)

    def set_task_repeat(self, task_id: int, repeat_after_seconds: int) -> dict[str, Any]:
        return self._record("set_task_repeat", task_id, repeat_after_seconds=repeat_after_seconds)

    def add_task_relation(self, task_id: int, other_task_id: int, relation_type: str) -> dict[str, Any]:
        return self._record("add_task_relation", task_id, other_task_id=other_task_id, relation_type=relation_type)

    def move_task(self, task_id: int, project_id: int) -> dict[str, Any]:
        return self._record("move_task", task_id, project_id=project_id)

    def add_task_attachment(self, task_id: int, *, url: str | None = None, filename: str | None = None, bytes_base64: str | None = None) -> dict[str, Any]:
        return self._record("add_task_attachment", task_id, url=url, filename=filename, bytes_base64=bytes_base64)

    def capabilities(self) -> dict[str, bool]:
        return {}


def test_mcp_adapter_uses_discovered_alias_for_list_projects():
    mcp = McpTaskTools(
        client=_FakeMcpClient(
            tools=["list_projects"],
            responses={"list_projects": {"result": [{"id": 10, "title": "Kitchen"}]}},
        )
    )
    lists = mcp.list_lists()
    assert lists and lists[0]["id"] == 10


def test_fallback_single_operation_when_mcp_tool_missing():
    mcp = McpTaskTools(client=_FakeMcpClient(tools=[], responses={}))
    rest = _FakeRest(calls=[])
    wrapper = FallbackTaskTools(primary=mcp, fallback=rest)
    out = wrapper.archive_list(11, archived=True)
    assert out["ok"] is True
    assert any(call[0] == "archive_list" for call in rest.calls)


def test_mcp_archive_list_uses_update_project_alias():
    mcp = McpTaskTools(
        client=_FakeMcpClient(
            tools=["get_project", "update_project"],
            responses={
                "get_project": {"id": 9, "title": "Kitchen", "description": ""},
                "update_project": {"id": 9, "is_archived": True},
            },
        )
    )
    out = mcp.archive_list(9, archived=True)
    assert out["id"] == 9


def test_fallback_single_operation_when_mcp_transport_fails():
    mcp = McpTaskTools(client=_FakeMcpClient(tools=["create_task"], responses={}, fail_calls=True))
    rest = _FakeRest(calls=[])
    wrapper = FallbackTaskTools(primary=mcp, fallback=rest)
    out = wrapper.create_task(9, title="Buy milk")
    assert out["ok"] is True
    assert any(call[0] == "create_task" for call in rest.calls)


def test_factory_modes(monkeypatch):
    import agents.task_agent.tools as tools_mod

    class _DummyMcp:
        def healthcheck(self):  # pragma: no cover - not used
            return HealthStatus(ok=True, backend_reachable=True, tools_discovered=["mcp.x"])

    class _DummyRest:
        def healthcheck(self):  # pragma: no cover - not used
            return HealthStatus(ok=True, backend_reachable=True, tools_discovered=["http.x"])

    monkeypatch.setattr(tools_mod, "McpTaskTools", _DummyMcp)
    monkeypatch.setattr(tools_mod, "RestTaskTools", _DummyRest)

    monkeypatch.setattr(tools_mod.task_settings, "task_agent_tools_backend", "rest")
    assert isinstance(task_tools(), _DummyRest)

    monkeypatch.setattr(tools_mod.task_settings, "task_agent_tools_backend", "mcp")
    assert isinstance(task_tools(), _DummyMcp)

    monkeypatch.setattr(tools_mod.task_settings, "task_agent_tools_backend", "auto")
    assert isinstance(task_tools(), FallbackTaskTools)


def test_mcp_only_mode_without_tools_fails_for_required_op():
    mcp = McpTaskTools(client=_FakeMcpClient(tools=[], responses={}))
    with pytest.raises(Exception):
        mcp.create_task(1, title="Task")
