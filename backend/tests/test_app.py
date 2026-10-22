"""Tests for the running app: health check and error format."""


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "database": "connected"}


def test_unknown_address_uses_contract_error_format(client):
    r = client.get("/api/does-not-exist")
    assert r.status_code == 404
    assert r.json()["error"] == "not_found"
    assert "message" in r.json()
