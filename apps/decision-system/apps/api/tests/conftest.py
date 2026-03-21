import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = next((parent for parent in Path(__file__).resolve().parents if (parent / "agents").exists()), None)
if ROOT is not None and str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.db import get_db
from app.main import app
from app.models.base import Base
from app.models import agent_sessions, entities, family_dna, files, identity, memory, notes  # noqa: F401


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


@compiles(UUID, "sqlite")
def _compile_uuid_sqlite(_type, _compiler, **_kwargs):
    return "TEXT"


engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
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
    monkeypatch.setattr("app.routers.decisions._emit_decision_event", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.routers.goals._emit_goal_event", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.routers.roadmap.publish_event", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.services.family_dna.publish_event", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.services.ops._post_canonical_event", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.routers.files.emit_canonical_event", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.routers.notes.emit_canonical_event", lambda *args, **kwargs: None)
    yield


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
