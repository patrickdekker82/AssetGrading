import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from app.db import get_engine
from app.settings import get_settings


@pytest.fixture
def client(test_database_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    monkeypatch.setenv("SCHEDULER_ENABLED", "true")
    get_settings.cache_clear()
    get_engine.cache_clear()
    from app.main import app

    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()
    get_engine.cache_clear()


def test_health_reports_ok(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["model_version"] == "0.1.0"
    assert body["scheduler_running"] is True
    assert body["compute_ok"] is True


def test_tabs_endpoint_lists_nine_tabs(client):
    tabs = client.get("/api/tabs").json()
    assert len(tabs) == 9
    assert tabs[0]["slug"] == "crypto"
    assert "Bitcoin" in tabs[0]["template_names"]


def test_glossary_endpoint(client):
    body = client.get("/api/glossary").json()
    assert body["terms"]["datadekking"]["label"] == "Datadekking"


def test_model_endpoint(client):
    body = client.get("/api/model").json()
    assert len(body["templates"]) == 16


def test_model_version_is_registered_and_append_only(client, test_database_url):
    engine = create_engine(test_database_url)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT version FROM model_version")).scalars().all() == ["0.1.0"]
        with pytest.raises(DBAPIError, match="append-only"):
            conn.execute(text("UPDATE model_version SET description = 'x'"))
    engine.dispose()
