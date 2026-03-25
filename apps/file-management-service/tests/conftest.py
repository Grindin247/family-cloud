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
from pgvector.sqlalchemy import Vector
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import get_db
from app.main import app
from app.models import documents  # noqa: F401
from app.models.base import Base


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


@compiles(UUID, "sqlite")
def _compile_uuid_sqlite(_type, _compiler, **_kwargs):
    return "TEXT"


@compiles(Vector, "sqlite")
def _compile_vector_sqlite(_type, _compiler, **_kwargs):
    return "BLOB"


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
    context = {
        "family_id": 2,
        "family_slug": "test-family",
        "person_id": "00000000-0000-0000-0000-000000000010",
        "actor_person_id": "00000000-0000-0000-0000-000000000010",
        "target_person_id": "00000000-0000-0000-0000-000000000010",
        "is_family_admin": True,
        "primary_email": "admin@example.com",
        "directory_account_id": "dir-10",
        "member_id": 10,
    }
    monkeypatch.setattr("app.routers.files.ensure_family_access", lambda **kwargs: None)
    monkeypatch.setattr("app.routers.files.ensure_files_enabled", lambda **kwargs: None)
    monkeypatch.setattr("app.routers.notes.ensure_family_access", lambda **kwargs: None)
    monkeypatch.setattr("app.routers.notes.ensure_files_enabled", lambda **kwargs: None)
    monkeypatch.setattr("app.routers.search.ensure_family_access", lambda **kwargs: None)
    monkeypatch.setattr("app.routers.search.ensure_files_enabled", lambda **kwargs: None)
    monkeypatch.setattr("app.routers.jobs.ensure_family_access", lambda **kwargs: None)
    monkeypatch.setattr("app.routers.jobs.ensure_files_enabled", lambda **kwargs: None)
    monkeypatch.setattr("app.routers.files.get_family_context", lambda **kwargs: context)
    monkeypatch.setattr("app.routers.notes.get_family_context", lambda **kwargs: context)
    monkeypatch.setattr("app.routers.search.get_family_context", lambda **kwargs: context)
    monkeypatch.setattr("app.routers.files.emit_canonical_event", lambda **kwargs: "evt-file")
    monkeypatch.setattr("app.routers.notes.emit_canonical_event", lambda **kwargs: "evt-note")
    monkeypatch.setattr("app.services.jobs.question_api.create_question", lambda **kwargs: {"question_id": "q-1"})
    monkeypatch.setattr("app.services.jobs.decision_api.write_family_memory", lambda **kwargs: None)
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
