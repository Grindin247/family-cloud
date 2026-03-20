from __future__ import annotations

import sys
import types
from pathlib import Path

MCP_DIR = Path(__file__).resolve().parents[1]
if str(MCP_DIR) not in sys.path:
    sys.path.insert(0, str(MCP_DIR))


class _FakeFastMCP:
    def __init__(self, name: str):
        self.name = name

    def tool(self):
        def decorator(fn):
            return fn

        return decorator


fake_fastmcp = types.ModuleType("mcp.server.fastmcp")
fake_fastmcp.FastMCP = _FakeFastMCP
sys.modules["mcp"] = types.ModuleType("mcp")
sys.modules["mcp.server"] = types.ModuleType("mcp.server")
sys.modules["mcp.server.fastmcp"] = fake_fastmcp

import server


def test_family_event_tools_map_queries(monkeypatch):
    calls: list[tuple[str, str, dict, str]] = []

    def fake_request(method: str, path: str, actor_id: str, actor_name: str | None, body=None, query=None):
        calls.append((method, path, query or {}, actor_id))
        return {"body": {"ok": True}}

    monkeypatch.setattr(server, "_event_request", fake_request)

    server.get_family_event_counts(
        family_id=2,
        actor_id="reader@example.com",
        domain="task",
        domains=["task", "note"],
        event_type="task.completed",
        tag="church",
        start="2026-03-01T00:00:00Z",
        end="2026-03-31T23:59:59Z",
    )
    server.get_family_event_time_series(
        family_id=2,
        actor_id="reader@example.com",
        metric="events.count",
        bucket="week",
        domain="task",
        domains=["task"],
        event_type="task.completed",
        tag="household",
    )
    server.get_family_event_domain_summary(family_id=2, actor_id="reader@example.com")
    server.compare_family_event_periods(
        family_id=2,
        actor_id="reader@example.com",
        metric="tasks.completed.count",
        current_start="2026-03-08T00:00:00Z",
        current_end="2026-03-14T23:59:59Z",
        baseline_start="2026-03-01T00:00:00Z",
        baseline_end="2026-03-07T23:59:59Z",
        tag="household",
    )
    server.get_family_event_sequences(
        family_id=2,
        actor_id="reader@example.com",
        anchor_event_id="evt-1",
        before_limit=3,
        after_limit=4,
    )
    server.get_family_event_top_tags(family_id=2, actor_id="reader@example.com", limit=7)
    server.get_family_event_data_quality(family_id=2, actor_id="reader@example.com")

    assert calls[0] == (
        "GET",
        "/analytics/counts",
        {
            "family_id": 2,
            "domain": "task",
            "domains": ["task", "note"],
            "event_type": "task.completed",
            "tag": "church",
            "start": "2026-03-01T00:00:00Z",
            "end": "2026-03-31T23:59:59Z",
        },
        "reader@example.com",
    )
    assert calls[1][1] == "/analytics/time-series"
    assert calls[1][2]["metric"] == "events.count"
    assert calls[1][2]["bucket"] == "week"
    assert calls[2][1] == "/analytics/domain-summary"
    assert calls[3][1] == "/analytics/compare-periods"
    assert calls[3][2]["tag"] == "household"
    assert calls[4] == (
        "GET",
        "/analytics/sequences",
        {"family_id": 2, "before_limit": 3, "after_limit": 4, "anchor_event_id": "evt-1"},
        "reader@example.com",
    )
    assert calls[5] == (
        "GET",
        "/analytics/top-tags",
        {"family_id": 2, "limit": 7},
        "reader@example.com",
    )
    assert calls[6] == (
        "GET",
        "/analytics/data-quality",
        {"family_id": 2},
        "reader@example.com",
    )


def test_identity_tools_map_queries(monkeypatch):
    calls: list[tuple[str, str, dict | None, dict | None, str]] = []

    def fake_request(method: str, path: str, actor_id: str, actor_name: str | None, body=None, query=None):
        calls.append((method, path, query, body, actor_id))
        return {"body": {"ok": True}}

    monkeypatch.setattr(server, "_request", fake_request)

    server.list_family_persons(family_id=2, actor_id="admin@example.com")
    server.get_resolved_context(
        family_id=2,
        actor_id="admin@example.com",
        target_person_id="person-2",
        source_channel="discord",
        source_sender_id="sender-1",
    )
    server.resolve_person_alias(family_id=2, actor_id="admin@example.com", alias="dad")
    server.resolve_sender_identity(
        family_id=2,
        actor_id="admin@example.com",
        source_channel="discord",
        source_sender_id="sender-1",
    )
    server.list_family_features(family_id=2, actor_id="admin@example.com")

    assert calls[0] == ("GET", "/families/2/persons", None, None, "admin@example.com")
    assert calls[1] == (
        "GET",
        "/families/2/context",
        {"target_person_id": "person-2", "source_channel": "discord", "source_sender_id": "sender-1"},
        None,
        "admin@example.com",
    )
    assert calls[2] == ("GET", "/families/2/resolve-alias", {"q": "dad"}, None, "admin@example.com")
    assert calls[3] == (
        "POST",
        "/identity/resolve-sender",
        None,
        {"family_id": 2, "source_channel": "discord", "source_sender_id": "sender-1"},
        "admin@example.com",
    )
    assert calls[4] == ("GET", "/families/2/features", None, None, "admin@example.com")
