import os
import sys
from pathlib import Path

os.environ["APP_ENV"] = "test"

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))
REPO_ROOT = next((parent for parent in APP_ROOT.parents if (parent / "docker-compose.yml").exists()), APP_ROOT)
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.db import get_db
from app.main import app
from app.models.base import Base
from app.models import conversations  # noqa: F401


engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
def reset_db(monkeypatch, tmp_path):
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    runtime_calls: list[dict] = []
    broadcast_events: list[dict] = []

    people = [
        {
            "person_id": "person-admin",
            "display_name": "Admin User",
            "accounts": {"email": ["admin@example.com"]},
        },
        {
            "person_id": "person-partner",
            "display_name": "Partner User",
            "accounts": {"email": ["partner@example.com"]},
        },
        {
            "person_id": "person-kid",
            "display_name": "Kid User",
            "accounts": {"email": ["kid@example.com"]},
        },
    ]

    def fake_family_context(**kwargs):
        actor_email = kwargs.get("actor_email") or "admin@example.com"
        actor_person_id = "person-admin"
        if actor_email == "partner@example.com":
            actor_person_id = "person-partner"
        elif actor_email == "kid@example.com":
            actor_person_id = "person-kid"
        return {
            "family_id": 2,
            "family_slug": "callender",
            "actor_person_id": actor_person_id,
            "target_person_id": actor_person_id,
            "is_family_admin": actor_email != "kid@example.com",
        }

    def fake_get_me(**kwargs):
        actor_email = kwargs.get("actor_email") or "admin@example.com"
        return {
            "authenticated": True,
            "email": actor_email,
            "memberships": [{"family_id": 2, "family_name": "Callender", "member_id": 1, "role": "admin"}],
        }

    async def fake_broadcast(*, family_id, conversation_id, event):
        broadcast_events.append({"family_id": family_id, "conversation_id": conversation_id, "event": event})

    def fake_run_turn(*, assistant_id, conversation_id, transport_message):
        runtime_calls.append(
            {
                "assistant_id": assistant_id,
                "conversation_id": conversation_id,
                "transport_message": transport_message,
            }
        )
        return {
            "assistant_text": f"{assistant_id.title()} reply for {conversation_id}",
            "provider": "gateway",
            "raw": {"result": {"payloads": [{"text": f"{assistant_id.title()} reply for {conversation_id}"}]}},
        }

    monkeypatch.setattr(settings, "uploads_dir", str(tmp_path / "uploads"))
    monkeypatch.setattr("app.services.decision_api.ensure_family_access", lambda **kwargs: None)
    monkeypatch.setattr("app.routers.conversations.ensure_family_access", lambda **kwargs: None)
    monkeypatch.setattr("app.services.decision_api.get_me", fake_get_me)
    monkeypatch.setattr("app.routers.conversations.get_me", fake_get_me)
    monkeypatch.setattr("app.services.decision_api.get_family_context", fake_family_context)
    monkeypatch.setattr("app.routers.conversations.get_family_context", fake_family_context)
    monkeypatch.setattr("app.services.decision_api.get_family_persons", lambda **kwargs: people)
    monkeypatch.setattr("app.routers.conversations.get_family_persons", lambda **kwargs: people)
    monkeypatch.setattr("app.routers.conversations.runtime_adapter.run_turn", fake_run_turn)
    monkeypatch.setattr("app.routers.conversations.realtime_manager.broadcast", fake_broadcast)
    monkeypatch.setattr("app.routers.conversations.SessionLocal", TestingSessionLocal)
    yield {"runtime_calls": runtime_calls, "broadcast_events": broadcast_events}


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client
