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
from app.main import app
from app.models.base import Base
from app.models import education  # noqa: F401
from app.services.education import ensure_seed_data


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
    db = TestingSessionLocal()
    ensure_seed_data(db)
    db.close()
    monkeypatch.setattr("app.routers.education.ensure_family_access", lambda **kwargs: None)
    monkeypatch.setattr("app.routers.education.ensure_education_enabled", lambda **kwargs: None)
    monkeypatch.setattr(
        "app.routers.education.get_family_person",
        lambda **kwargs: {
            "person_id": kwargs["learner_id"],
            "display_name": "Learner One",
            "canonical_name": "Learner One",
        },
    )
    monkeypatch.setattr("app.services.education.publish_family_event", lambda *args, **kwargs: "evt-1")
    yield


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client
