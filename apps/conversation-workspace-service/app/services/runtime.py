from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Any

from app.core.config import settings
from app.core.errors import raise_api_error

ASSISTANT_AGENT_IDS = {
    "caleb": "main",
    "amelia": "amelia",
}


class OpenClawRuntimeAdapter:
    @staticmethod
    def _build_session_id(conversation_id: str, assistant_id: str) -> str:
        raw_value = f"conversation-{conversation_id}-{assistant_id}"
        safe_value = re.sub(r"[^A-Za-z0-9_-]+", "-", raw_value).strip("-")
        return safe_value[:120] or "conversation"

    @staticmethod
    def _extract_payload_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
        result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
        items = result.get("payloads") if isinstance(result.get("payloads"), list) else []
        if not items and isinstance(payload.get("payloads"), list):
            items = payload.get("payloads") or []
        return [item for item in items if isinstance(item, dict)]

    @staticmethod
    def _extract_payload_meta(payload: dict[str, Any]) -> dict[str, Any]:
        result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
        meta = result.get("meta") if isinstance(result.get("meta"), dict) else {}
        if not meta and isinstance(payload.get("meta"), dict):
            meta = payload.get("meta") or {}
        return meta

    @staticmethod
    def _extract_stop_reason(payload: dict[str, Any]) -> str:
        meta = OpenClawRuntimeAdapter._extract_payload_meta(payload)
        return str(meta.get("stopReason") or "").strip().lower()

    @staticmethod
    def _extract_runtime_session_id(payload: dict[str, Any]) -> str:
        meta = OpenClawRuntimeAdapter._extract_payload_meta(payload)
        agent_meta = meta.get("agentMeta") if isinstance(meta.get("agentMeta"), dict) else {}
        return str(agent_meta.get("sessionId") or "").strip()

    @staticmethod
    def _clean_assistant_text(text: str) -> str:
        cleaned = re.sub(r"^\[\[reply_to_current\]\]\s*", "", text.strip())
        return cleaned.strip()

    def _extract_assistant_text(self, payload: dict[str, Any]) -> str:
        text_parts: list[str] = []
        for item in self._extract_payload_items(payload):
            text = self._clean_assistant_text(str(item.get("text") or ""))
            if text:
                text_parts.append(text)
        return "\n\n".join(text_parts).strip()

    def _session_log_path(self, *, agent_id: str, session_id: str) -> Path:
        return Path(settings.openclaw_home) / ".openclaw" / "agents" / agent_id / "sessions" / f"{session_id}.jsonl"

    def _session_logs_dir(self, *, agent_id: str) -> Path:
        return Path(settings.openclaw_home) / ".openclaw" / "agents" / agent_id / "sessions"

    @staticmethod
    def _parse_timestamp(value: Any) -> datetime | None:
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None

    @staticmethod
    def _content_phase(content: dict[str, Any]) -> str:
        signature = content.get("textSignature")
        if not isinstance(signature, str) or not signature.strip():
            return ""
        try:
            parsed = json.loads(signature)
        except json.JSONDecodeError:
            return ""
        return str(parsed.get("phase") or "").strip().lower()

    def _read_followup_final_answer(
        self,
        *,
        agent_id: str,
        session_id: str,
        since: datetime | None = None,
        transport_message: str | None = None,
    ) -> str | None:
        session_log = self._session_log_path(agent_id=agent_id, session_id=session_id)
        if not session_log.exists():
            return None
        return self._extract_final_answer_from_session_log(
            session_log=session_log,
            since=since,
            transport_message=transport_message,
        )

    def _extract_final_answer_from_session_log(
        self,
        *,
        session_log: Path,
        since: datetime | None,
        transport_message: str | None,
    ) -> str | None:
        latest_text: tuple[datetime, str] | None = None
        matched_user_timestamp = since
        with session_log.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    event = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue
                if str(event.get("type") or "") != "message":
                    continue
                message = event.get("message")
                if not isinstance(message, dict):
                    continue
                timestamp = self._parse_timestamp(event.get("timestamp")) or self._parse_timestamp(message.get("timestamp"))
                if since is not None and (timestamp is None or timestamp < since):
                    continue
                if str(message.get("role") or "") == "user" and transport_message:
                    for content in message.get("content") or []:
                        if not isinstance(content, dict) or str(content.get("type") or "") != "text":
                            continue
                        text = str(content.get("text") or "")
                        if transport_message in text:
                            matched_user_timestamp = timestamp or since
                if str(message.get("role") or "") != "assistant":
                    continue
                if matched_user_timestamp is None:
                    continue
                for content in message.get("content") or []:
                    if not isinstance(content, dict) or str(content.get("type") or "") != "text":
                        continue
                    if self._content_phase(content) != "final_answer":
                        continue
                    text = self._clean_assistant_text(str(content.get("text") or ""))
                    if not text or text == "NO_REPLY":
                        continue
                    if latest_text is None or timestamp >= latest_text[0]:
                        latest_text = (timestamp, text)
        return latest_text[1] if latest_text else None

    def _read_recent_followup_final_answer(
        self,
        *,
        agent_id: str,
        since: datetime,
        transport_message: str,
    ) -> str | None:
        sessions_dir = self._session_logs_dir(agent_id=agent_id)
        if not sessions_dir.exists():
            return None
        candidates = sorted(
            (
                path
                for path in sessions_dir.glob("*.jsonl")
                if path.is_file()
                and path.name != "sessions.json"
                and datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc) >= since
            ),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for session_log in candidates[:20]:
            final_text = self._extract_final_answer_from_session_log(
                session_log=session_log,
                since=since,
                transport_message=transport_message,
            )
            if final_text:
                return final_text
        return None

    def _wait_for_followup_final_answer(
        self,
        *,
        agent_id: str,
        session_id: str,
        since: datetime,
        transport_message: str,
    ) -> str | None:
        deadline = time.monotonic() + max(1, settings.openclaw_followup_timeout_seconds)
        poll_interval = max(0.1, settings.openclaw_followup_poll_interval_seconds)
        while time.monotonic() < deadline:
            final_text = self._read_followup_final_answer(
                agent_id=agent_id,
                session_id=session_id,
                since=since,
                transport_message=transport_message,
            )
            if not final_text:
                final_text = self._read_recent_followup_final_answer(
                    agent_id=agent_id,
                    since=since,
                    transport_message=transport_message,
                )
            if final_text:
                return final_text
            time.sleep(poll_interval)
        return None

    def run_turn(
        self,
        *,
        assistant_id: str,
        conversation_id: str,
        transport_message: str,
    ) -> dict[str, Any]:
        agent_id = ASSISTANT_AGENT_IDS.get(assistant_id)
        if not agent_id:
            raise_api_error(400, "assistant_not_supported", "assistant is not supported", {"assistant_id": assistant_id})

        started_at = datetime.now(timezone.utc)
        command = [
            settings.openclaw_bin,
            "agent",
            "--agent",
            agent_id,
            "--channel",
            settings.openclaw_delivery_channel,
            "--session-id",
            self._build_session_id(conversation_id, assistant_id),
            "--message",
            transport_message,
            "--json",
            "--timeout",
            str(settings.openclaw_timeout_seconds),
        ]
        runtime_env = os.environ.copy()
        runtime_env["OPENCLAW_HOME"] = settings.openclaw_home
        runtime_env.setdefault("HOME", settings.openclaw_home)
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=settings.openclaw_timeout_seconds + 15,
            env=runtime_env,
        )
        if completed.returncode != 0:
            raise_api_error(
                502,
                "openclaw_runtime_failed",
                "OpenClaw agent turn failed",
                {"stderr": (completed.stderr or "").strip(), "stdout": (completed.stdout or "").strip()},
            )
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise_api_error(
                502,
                "openclaw_invalid_response",
                f"OpenClaw returned invalid JSON: {exc}",
            )
        assistant_text = self._extract_assistant_text(payload)
        stop_reason = self._extract_stop_reason(payload)
        runtime_session_id = self._extract_runtime_session_id(payload)
        if runtime_session_id and stop_reason and stop_reason != "stop":
            followup_text = self._wait_for_followup_final_answer(
                agent_id=agent_id,
                session_id=runtime_session_id,
                since=started_at,
                transport_message=transport_message,
            )
            if followup_text:
                assistant_text = followup_text
        if not assistant_text:
            assistant_text = "I finished the turn, but I did not get a readable text reply back from the runtime."
        return {
            "assistant_text": assistant_text,
            "provider": "gateway",
            "raw": payload,
        }
