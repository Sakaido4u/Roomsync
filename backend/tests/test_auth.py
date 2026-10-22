"""Login and "who am I" (contract endpoints 3 and 4)."""

from tests.conftest import PASSWORD


def test_login_returns_token_and_user(client, world):
    r = client.post("/api/auth/login", json={"college_id": "T1", "password": PASSWORD})
    assert r.status_code == 200
    body = r.json()
    assert body["token"]
    assert body["user"]["college_id"] == "T1"
    assert body["user"]["role"] == "teacher"
    assert "password_hash" not in body["user"]


def test_wrong_password_and_unknown_id_look_the_same(client, world):
    wrong_pw = client.post("/api/auth/login", json={"college_id": "T1", "password": "nope"})
    unknown = client.post("/api/auth/login", json={"college_id": "NOBODY", "password": "nope"})
    assert wrong_pw.status_code == unknown.status_code == 401
    assert wrong_pw.json() == unknown.json()
    assert wrong_pw.json()["error"] == "not_logged_in"


def test_account_without_password_cannot_log_in(client, world, db):
    world["teacher"].password_hash = None
    db.commit()
    r = client.post("/api/auth/login", json={"college_id": "T1", "password": PASSWORD})
    assert r.status_code == 401


def test_me_with_token(client, login):
    r = client.get("/api/auth/me", headers=login("student"))
    assert r.status_code == 200
    assert r.json()["role"] == "student"
    assert r.json()["class_id"] == "CSE-7A"


def test_me_without_token(client, world):
    r = client.get("/api/auth/me")
    assert r.status_code == 401
    assert r.json()["error"] == "not_logged_in"


def test_me_with_fake_token(client, world):
    r = client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert r.status_code == 401


def test_missing_field_gives_400_invalid_input(client, world):
    r = client.post("/api/auth/login", json={"college_id": "T1"})
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_input"
    assert "password" in r.json()["message"]
