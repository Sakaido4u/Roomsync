"""Tests for the running app: health check and error format."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.database import get_db
from app.main import app


@pytest.fixture()
def client(engine, db):
    # Point the app at the test database instead of the real one.
    test_session = sessionmaker(bind=engine)

    def override_get_db():
        session = test_session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "database": "connected"}


def test_unknown_address_uses_contract_error_format(client):
    r = client.get("/api/does-not-exist")
    assert r.status_code == 404
    assert r.json()["error"] == "not_found"
    assert "message" in r.json()
