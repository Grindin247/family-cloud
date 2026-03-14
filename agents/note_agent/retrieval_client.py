from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from .settings import note_settings


class NoteRetrievalError(RuntimeError):
    pass


@dataclass
class NoteRetrievalClient:
    base_url: str = note_settings.decision_api_base_url

    def _post(self, path: str, *, payload: dict[str, Any], actor: str) -> dict[str, Any]:
        url = f"{self.base_url.rstrip('/')}{path}"
        with httpx.Client(timeout=note_settings.http_timeout_seconds) as client:
            response = client.post(url, json=payload, headers={"X-Dev-User": actor})
        if response.status_code >= 400:
            raise NoteRetrievalError(f"note retrieval backend error {response.status_code}: {response.text[:200]}")
        data = response.json()
        if not isinstance(data, dict):
            raise NoteRetrievalError("note retrieval backend returned non-object payload")
        return data

    def index_note(self, *, payload: dict[str, Any], actor: str) -> dict[str, Any]:
        return self._post("/notes/index", payload=payload, actor=actor)

    def search_notes(self, *, payload: dict[str, Any], actor: str) -> dict[str, Any]:
        return self._post("/notes/search", payload=payload, actor=actor)
