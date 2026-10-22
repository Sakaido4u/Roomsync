"""Limit on wrong logins: 10 per college ID per 15 minutes."""

import datetime as dt

import pytest
from sqlalchemy import select, update

from app.config import IST
from app.models import LoginFailure
from app.routers import auth
from tests.conftest import PASSWORD


def log_in(client, password, college_id="T1"):
    return client.post("/api/auth/login", json={"college_id": college_id, "password": password})


def fail(client, times, college_id="T1"):
    for _ in range(times):
        assert log_in(client, "wrong-password", college_id).status_code == 401


def age_failures(db, minutes):
    db.execute(update(LoginFailure).values(time=LoginFailure.time - dt.timedelta(minutes=minutes)))
    db.commit()


def test_ten_wrong_tries_lock_the_id_even_for_the_right_password(client, world):
    fail(client, 10)
    r = log_in(client, PASSWORD)
    assert r.status_code == 401
    body = r.json()
    assert body["error"] == "not_logged_in"
    assert body["message"].startswith("Too many failed logins for this ID. Try again in 15 minutes")


def test_nine_wrong_tries_still_allow_login(client, world):
    fail(client, 9)
    assert log_in(client, PASSWORD).status_code == 200


def test_successful_login_resets_the_count(client, world):
    fail(client, 9)
    log_in(client, PASSWORD)
    fail(client, 9)
    assert log_in(client, PASSWORD).status_code == 200


def test_lock_lifts_after_15_minutes(client, world, db):
    fail(client, 10)
    age_failures(db, 14)
    r = log_in(client, PASSWORD)
    assert "Try again in 1 minute," in r.json()["message"]
    age_failures(db, 1)
    assert log_in(client, PASSWORD).status_code == 200


def test_old_failures_are_forgotten(client, world, db):
    fail(client, 6)
    age_failures(db, 15)
    fail(client, 6)
    assert log_in(client, PASSWORD).status_code == 200
    db.expire_all()
    # The 6 old ones were deleted; the 6 new ones were cleared by the login.
    assert db.scalars(select(LoginFailure)).all() == []


def test_other_ids_are_not_affected(client, world):
    fail(client, 10, "T1")
    assert log_in(client, PASSWORD, "T2").status_code == 200


def test_made_up_ids_are_limited_the_same_way(client, world):
    fail(client, 10, "NOBODY")
    r = log_in(client, "anything", "NOBODY")
    assert r.json()["message"].startswith("Too many failed logins")


def test_new_password_from_setup_code_unlocks(client, world, monkeypatch):
    codes = []
    monkeypatch.setattr(auth, "deliver_code", lambda user, code: codes.append(code))
    fail(client, 10)
    client.post("/api/auth/request-setup", json={"college_id": "T1"})
    r = client.post("/api/auth/set-password",
                    json={"college_id": "T1", "code": codes[0], "new_password": "fresh-pass-1"})
    assert r.status_code == 200
    assert log_in(client, "fresh-pass-1").status_code == 200


@pytest.mark.parametrize("college_id", ["T1", " T1 "])
def test_spaces_around_the_id_count_as_the_same_id(client, world, college_id):
    fail(client, 10, "T1")
    assert log_in(client, PASSWORD, college_id).status_code == 401
