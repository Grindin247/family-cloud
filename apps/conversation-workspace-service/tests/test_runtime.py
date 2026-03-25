import json
from datetime import datetime, timedelta, timezone
import subprocess

from app.core.config import settings
from app.services.runtime import OpenClawRuntimeAdapter


def test_runtime_uses_safe_session_id_and_openclaw_home(monkeypatch):
    captured: dict = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(
            command,
            0,
            stdout='{"payloads":[{"text":"Caleb handled it."}]}',
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(settings, "openclaw_home", "/tmp/openclaw-home")
    monkeypatch.setattr(settings, "openclaw_bin", "openclaw")
    monkeypatch.setattr(settings, "openclaw_timeout_seconds", 15)
    monkeypatch.setattr(settings, "openclaw_delivery_channel", "discord")

    adapter = OpenClawRuntimeAdapter()
    result = adapter.run_turn(
        assistant_id="caleb",
        conversation_id="123e4567-e89b-12d3-a456-426614174000",
        transport_message="hello",
    )

    assert result["assistant_text"] == "Caleb handled it."
    assert captured["command"][0] == "openclaw"
    session_id = captured["command"][captured["command"].index("--session-id") + 1]
    assert session_id == "conversation-123e4567-e89b-12d3-a456-426614174000-caleb"
    assert ":" not in session_id
    assert captured["kwargs"]["env"]["OPENCLAW_HOME"] == "/tmp/openclaw-home"


def test_runtime_reads_nested_payloads(monkeypatch):
    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(
            command,
            0,
            stdout='{"result":{"payloads":[{"text":"Amelia nested reply."}]}}',
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    adapter = OpenClawRuntimeAdapter()

    result = adapter.run_turn(
        assistant_id="amelia",
        conversation_id="conversation-id",
        transport_message="hello",
    )

    assert result["assistant_text"] == "Amelia nested reply."


def test_runtime_waits_for_followup_final_answer(monkeypatch, tmp_path):
    session_id = "session-123"
    session_log = tmp_path / ".openclaw" / "agents" / "amelia" / "sessions" / f"{session_id}.jsonl"
    session_log.parent.mkdir(parents=True, exist_ok=True)

    def fake_run(command, **kwargs):
        now = datetime.now(timezone.utc)
        entries = [
            {
                "type": "message",
                "timestamp": now.isoformat().replace("+00:00", "Z"),
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "text",
                            "text": "Checking your live planning data.",
                            "textSignature": json.dumps({"phase": "commentary"}),
                        }
                    ],
                },
            },
            {
                "type": "message",
                "timestamp": (now + timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "text",
                            "text": "[[reply_to_current]] Your workout plan is bench day.",
                            "textSignature": json.dumps({"phase": "final_answer"}),
                        }
                    ],
                },
            },
        ]
        session_log.write_text("\n".join(json.dumps(entry) for entry in entries) + "\n", encoding="utf-8")
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {
                    "result": {
                        "payloads": [{"text": "Checking your live planning data."}],
                        "meta": {
                            "agentMeta": {"sessionId": session_id},
                            "stopReason": "end_turn",
                        },
                    }
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(settings, "openclaw_home", str(tmp_path))
    monkeypatch.setattr(settings, "openclaw_followup_timeout_seconds", 1)
    monkeypatch.setattr(settings, "openclaw_followup_poll_interval_seconds", 0.01)

    adapter = OpenClawRuntimeAdapter()
    result = adapter.run_turn(
        assistant_id="amelia",
        conversation_id="conversation-id",
        transport_message="hello",
    )

    assert result["assistant_text"] == "Your workout plan is bench day."


def test_runtime_finds_followup_in_recent_related_session(monkeypatch, tmp_path):
    primary_session_id = "session-primary"
    sessions_dir = tmp_path / ".openclaw" / "agents" / "amelia" / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    primary_session_log = sessions_dir / f"{primary_session_id}.jsonl"
    related_session_log = sessions_dir / "session-related.jsonl"
    transport_message = "Transport: first-party family chat\nNew user message:\nI am James. What is my workout plan for today?"

    def fake_run(command, **kwargs):
        now = datetime.now(timezone.utc)
        primary_entries = [
            {
                "type": "message",
                "timestamp": now.isoformat().replace("+00:00", "Z"),
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "text",
                            "text": "Checking your live planning data.",
                            "textSignature": json.dumps({"phase": "commentary"}),
                        }
                    ],
                },
            }
        ]
        related_entries = [
            {
                "type": "message",
                "timestamp": now.isoformat().replace("+00:00", "Z"),
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": f"[Tue 2026-03-24 08:21 EDT] {transport_message}"}],
                },
            },
            {
                "type": "message",
                "timestamp": (now + timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "text",
                            "text": "[[reply_to_current]] Your workout plan is heavy bench day.",
                            "textSignature": json.dumps({"phase": "final_answer"}),
                        }
                    ],
                },
            },
        ]
        primary_session_log.write_text("\n".join(json.dumps(entry) for entry in primary_entries) + "\n", encoding="utf-8")
        related_session_log.write_text("\n".join(json.dumps(entry) for entry in related_entries) + "\n", encoding="utf-8")
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {
                    "payloads": [{"text": "Checking your live planning data."}],
                    "meta": {
                        "agentMeta": {"sessionId": primary_session_id},
                        "stopReason": "end_turn",
                    },
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(settings, "openclaw_home", str(tmp_path))
    monkeypatch.setattr(settings, "openclaw_followup_timeout_seconds", 1)
    monkeypatch.setattr(settings, "openclaw_followup_poll_interval_seconds", 0.01)

    adapter = OpenClawRuntimeAdapter()
    result = adapter.run_turn(
        assistant_id="amelia",
        conversation_id="conversation-id",
        transport_message=transport_message,
    )

    assert result["assistant_text"] == "Your workout plan is heavy bench day."
