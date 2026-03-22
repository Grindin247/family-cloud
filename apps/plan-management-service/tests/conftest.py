import os
import sys
from pathlib import Path

os.environ["APP_ENV"] = "test"

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import get_db
from app.core.errors import raise_api_error
from app.main import app
from app.models.base import Base
from app.models import planning  # noqa: F401


@compiles(UUID, "sqlite")
def _compile_uuid_sqlite(_type, _compiler, **_kwargs):
    return "TEXT"


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
def reset_db(monkeypatch):
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    queued_questions: list[dict] = []
    published_events: list[dict] = []

    monkeypatch.setattr("app.routers.planning.ensure_family_access", lambda **kwargs: None)
    monkeypatch.setattr("app.routers.planning.ensure_planning_enabled", lambda **kwargs: None)
    monkeypatch.setattr(
        "app.routers.planning.get_me",
        lambda **kwargs: {
            "authenticated": True,
            "email": "admin@example.com",
            "memberships": [
                {
                    "family_id": 2,
                    "family_name": "Test Family",
                    "member_id": 10,
                    "person_id": "00000000-0000-0000-0000-000000000010",
                    "role": "admin",
                }
            ],
        },
    )
    monkeypatch.setattr(
        "app.routers.planning.get_family_context",
        lambda **kwargs: {
            "family_id": kwargs["family_id"],
            "family_slug": "test-family",
            "person_id": "00000000-0000-0000-0000-000000000010",
            "actor_person_id": "00000000-0000-0000-0000-000000000010",
            "target_person_id": kwargs.get("target_person_id") or "00000000-0000-0000-0000-000000000010",
            "is_family_admin": True,
            "primary_email": "admin@example.com",
            "directory_account_id": "dir-10",
            "member_id": 10,
        },
    )
    monkeypatch.setattr(
        "app.routers.planning.get_family_persons",
        lambda **kwargs: [
            {
                "person_id": "00000000-0000-0000-0000-000000000010",
                "display_name": "Admin Person",
                "canonical_name": "Admin Person",
                "role_in_family": "admin",
                "is_admin": True,
                "status": "active",
                "accounts": {"email": ["admin@example.com"]},
            },
            {
                "person_id": "00000000-0000-0000-0000-000000000011",
                "display_name": "Second Person",
                "canonical_name": "Second Person",
                "role_in_family": "child",
                "is_admin": False,
                "status": "active",
                "accounts": {"email": ["child@example.com"]},
            },
            {
                "person_id": "00000000-0000-0000-0000-000000000012",
                "display_name": "Third Person",
                "canonical_name": "Third Person",
                "role_in_family": "adult",
                "is_admin": False,
                "status": "active",
                "accounts": {"email": ["adult@example.com"]},
            },
        ],
    )
    monkeypatch.setattr(
        "app.routers.planning.get_family_features",
        lambda **kwargs: [
            {
                "family_id": kwargs["family_id"],
                "feature_key": "planning",
                "enabled": True,
                "config": {},
                "updated_at": "2026-03-22T12:00:00Z",
            }
        ],
    )
    monkeypatch.setattr(
        "app.routers.planning.update_family_feature",
        lambda **kwargs: {
            "family_id": kwargs["family_id"],
            "feature_key": kwargs["feature_key"],
            "enabled": kwargs["enabled"],
            "config": kwargs["config"],
            "updated_at": "2026-03-22T12:00:00Z",
        },
    )
    monkeypatch.setattr(
        "app.routers.planning.list_goals",
        lambda **kwargs: [
            {
                "id": 11,
                "family_id": kwargs["family_id"],
                "scope_type": "family",
                "owner_person_id": None,
                "name": "Eat together four nights a week",
                "description": "Protect family dinners.",
                "status": "active",
                "weight": 0.7,
            },
            {
                "id": 12,
                "family_id": kwargs["family_id"],
                "scope_type": "person",
                "owner_person_id": "00000000-0000-0000-0000-000000000010",
                "name": "Build strength",
                "description": "Get stronger consistently.",
                "status": "active",
                "weight": 0.8,
            },
        ],
    )
    def _goal_lookup(**kwargs):
        if kwargs["goal_id"] not in {11, 12}:
            raise_api_error(404, "goal_not_found", "goal not found", {"goal_id": kwargs["goal_id"]})
        return {
            "id": kwargs["goal_id"],
            "family_id": 2,
            "scope_type": "family" if kwargs["goal_id"] == 11 else "person",
            "owner_person_id": None if kwargs["goal_id"] == 11 else "00000000-0000-0000-0000-000000000010",
            "name": "Eat together four nights a week" if kwargs["goal_id"] == 11 else "Build strength",
            "description": "Goal detail",
            "status": "active",
            "weight": 0.8,
        }

    monkeypatch.setattr("app.services.planning.get_goal", _goal_lookup)
    monkeypatch.setattr(
        "app.services.planning.profile_api.get_profile_detail",
        lambda **kwargs: {
            "person_id": kwargs["person_id"],
            "preferences": {
                "dietary_preferences": {"allergies": ["peanuts"] if kwargs["person_id"].endswith("11") else [], "restrictions": []},
                "accessibility_needs": {"accommodations": ["visual timer"] if kwargs["person_id"].endswith("10") else [], "notes": None},
                "learning_preferences": {"modalities": ["visual"] if kwargs["person_id"].endswith("11") else [], "notes": None},
                "motivation_style": {"encouragements": ["specific praise"] if kwargs["person_id"].endswith("10") else [], "notes": None},
                "communication_preferences": {"preferred_channels": ["text"] if kwargs["person_id"].endswith("10") else [], "notes": None},
            },
        },
    )

    def _queue_question(**kwargs):
        queued_questions.append(kwargs)
        return {"question": {"id": "q-1"}, "suppressed": False}

    monkeypatch.setattr("app.services.planning.question_api.create_question", _queue_question)
    monkeypatch.setattr("app.services.planning.publish_family_event", lambda event: published_events.append(event) or "evt-1")
    yield {"queued_questions": queued_questions, "published_events": published_events}


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def db_session():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
