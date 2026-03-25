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
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import get_db
from app.main import app
from app.models.base import Base
from app.models import questions  # noqa: F401


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
    published_events: list[dict] = []
    monkeypatch.setattr("app.services.decision_api.ensure_family_access", lambda **kwargs: None)
    monkeypatch.setattr("app.routers.questions.ensure_family_access", lambda **kwargs: None)
    monkeypatch.setattr(
        "app.services.decision_api.get_me",
        lambda **kwargs: {"authenticated": True, "email": "admin@example.com", "memberships": [{"family_id": 2, "family_name": "Callender", "member_id": 1, "role": "admin"}]},
    )
    monkeypatch.setattr(
        "app.services.decision_api.get_family_context",
        lambda **kwargs: {"family_id": 2, "family_slug": "callender", "member_id": 1, "is_family_admin": True, "persons": []},
    )
    monkeypatch.setattr("app.services.questions.publish_family_event", lambda event: published_events.append(event) or "evt-1")
    yield {"published_events": published_events}


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client
