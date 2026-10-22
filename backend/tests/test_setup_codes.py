"""First-login setup codes (contract endpoints 1 and 2).

Email sending is replaced by a fake that records the codes, so the tests
can read the code a real user would find in their inbox.
"""

import datetime as dt
import re

import pytest
from sqlalchemy import select

from app.config import IST
from app.models import SetupCode, User
from app.routers import auth

REPLY = {"message": "If this ID exists, a setup code has been sent to its college email."}


@pytest.fixture()
def inbox(monkeypatch):
    """Codes 'emailed' during the test, as (college_id, code)."""
    sent = []
    monkeypatch.setattr(auth, "deliver_code", lambda user, code: sent.append((user.college_id, code)))
    return sent


def request_code(client, college_id="T1"):
    return client.post("/api/auth/request-setup", json={"college_id": college_id})


def set_password(client, code, college_id="T1", password="new-secret-pw"):
    return client.post("/api/auth/set-password",
                       json={"college_id": college_id, "code": code, "new_password": password})


def log_in(client, password, college_id="T1"):
    return client.post("/api/auth/login", json={"college_id": college_id, "password": password})


def wrong(code: str) -> str:
    return f"{(int(code) + 1) % 1_000_000:06d}"


def make_older(db, seconds=120):
    """Pretend the latest code was requested a while ago."""
    db.expire_all()
    latest = db.scalar(select(SetupCode).order_by(SetupCode.id.desc()))
    latest.created_at = dt.datetime.now(IST) - dt.timedelta(seconds=seconds)
    db.commit()


# --- 1. Requesting a code ---------------------------------------------------

def test_request_sends_a_six_digit_code(client, world, inbox):
    r = request_code(client)
    assert r.status_code == 200
    assert r.json() == REPLY
    [(college_id, code)] = inbox
    assert college_id == "T1"
    assert re.fullmatch(r"\d{6}", code)


def test_code_is_stored_hashed_and_expires_in_15_minutes(client, world, inbox, db):
    request_code(client)
    [(_, code)] = inbox
    stored = db.scalar(select(SetupCode))
    assert code not in stored.code_hash
    assert stored.code_hash.startswith("$2")          # bcrypt
    left = stored.expires_at - dt.datetime.now(IST)
    assert dt.timedelta(minutes=14) < left <= dt.timedelta(minutes=15)


@pytest.mark.parametrize("college_id", ["NOBODY", "  "])
def test_unknown_id_gets_the_same_reply_and_no_email(client, world, inbox, college_id):
    r = request_code(client, college_id)
    if college_id.strip():
        assert r.status_code == 200
        assert r.json() == REPLY
    assert inbox == []


def test_inactive_account_gets_no_code(client, world, inbox, db):
    world["teacher"].is_active = False
    db.commit()
    assert request_code(client).json() == REPLY
    assert inbox == []


def test_no_second_email_within_a_minute(client, world, inbox):
    request_code(client)
    r = request_code(client)
    assert r.json() == REPLY
    assert len(inbox) == 1


def test_new_code_cancels_the_old_one(client, world, inbox, db):
    request_code(client)
    make_older(db)
    request_code(client)
    (_, old), (_, new) = inbox
    assert set_password(client, old).status_code == 400
    assert set_password(client, new).status_code == 200


def test_missing_college_id(client, world):
    r = client.post("/api/auth/request-setup", json={})
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_input"


# --- 2. Setting the password ------------------------------------------------

def test_set_password_with_code_then_log_in(client, world, inbox):
    request_code(client)
    [(_, code)] = inbox
    r = set_password(client, code, password="brand-new-pw")
    assert r.status_code == 200, r.text
    assert r.json() == {"message": "Password set. You can now log in."}
    assert log_in(client, "brand-new-pw").status_code == 200
    assert log_in(client, "pass1234").status_code == 401    # the old password is gone


def test_works_for_an_account_with_no_password_yet(client, world, inbox, db):
    world["teacher2"].password_hash = None
    db.commit()
    assert log_in(client, "anything1", "T2").status_code == 401
    request_code(client, "T2")
    [(_, code)] = inbox
    assert set_password(client, code, "T2", "first-password").status_code == 200
    assert log_in(client, "first-password", "T2").status_code == 200


def test_code_works_only_once(client, world, inbox):
    request_code(client)
    [(_, code)] = inbox
    set_password(client, code)
    r = set_password(client, code, password="another-pw-1")
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_input"


def test_wrong_code_is_refused(client, world, inbox):
    request_code(client)
    [(_, code)] = inbox
    r = set_password(client, wrong(code))
    assert r.status_code == 400
    assert r.json()["message"].startswith("Wrong or expired code")


def test_five_wrong_guesses_kill_the_code(client, world, inbox, db):
    request_code(client)
    [(_, code)] = inbox
    for _ in range(4):
        assert set_password(client, wrong(code)).status_code == 400
    assert set_password(client, code).status_code == 200    # 4 wrong guesses: still fine

    make_older(db)
    request_code(client)
    code = inbox[-1][1]
    for _ in range(5):
        set_password(client, wrong(code))
    assert set_password(client, code).status_code == 400    # 5th wrong guess ended it


def test_expired_code_is_refused(client, world, inbox, db):
    request_code(client)
    [(_, code)] = inbox
    stored = db.scalar(select(SetupCode))
    stored.expires_at = dt.datetime.now(IST) - dt.timedelta(seconds=1)
    db.commit()
    assert set_password(client, code).status_code == 400


def test_unknown_id_gets_the_same_error(client, world, inbox):
    request_code(client)
    [(_, code)] = inbox
    r = set_password(client, code, college_id="NOBODY")
    assert r.status_code == 400
    assert r.json()["message"].startswith("Wrong or expired code")


def test_codes_belong_to_one_account(client, world, inbox):
    request_code(client, "T1")
    [(_, code)] = inbox
    assert set_password(client, code, college_id="T2").status_code == 400


@pytest.mark.parametrize("password", ["short", "1234567"])
def test_password_needs_8_characters(client, world, inbox, db, password):
    request_code(client)
    [(_, code)] = inbox
    r = set_password(client, code, password=password)
    assert r.status_code == 400
    assert "new_password" in r.json()["message"]
    # A rejected password does not use up a guess.
    assert db.scalar(select(SetupCode)).attempts == 0
    assert set_password(client, code).status_code == 200


def test_too_long_password(client, world, inbox, db):
    request_code(client)
    [(_, code)] = inbox
    r = set_password(client, code, password="x" * 73)
    assert r.status_code == 400
    assert "too long" in r.json()["message"]
    assert db.scalar(select(SetupCode)).attempts == 0


@pytest.mark.parametrize("code", ["12345", "1234567", "abcdef", ""])
def test_code_must_be_six_digits(client, world, code):
    assert set_password(client, code).status_code == 400


def test_password_is_stored_hashed(client, world, inbox, db):
    request_code(client)
    [(_, code)] = inbox
    set_password(client, code, password="brand-new-pw")
    db.expire_all()
    stored = db.scalar(select(User).where(User.college_id == "T1")).password_hash
    assert "brand-new-pw" not in stored


# --- Delivering the code ----------------------------------------------------

def test_code_email_goes_to_the_college_email(monkeypatch, world):
    sent = []
    monkeypatch.setattr(auth, "email_enabled", lambda: True)
    monkeypatch.setattr(auth, "send_emails", lambda emails: sent.extend(emails))
    auth.deliver_code(world["teacher"], "123456")
    [email] = sent
    assert email.to == "t1@example.com"
    assert "123456" in email.body
    assert "15 minutes" in email.body


def test_without_email_setup_the_code_is_logged(monkeypatch, world, caplog):
    monkeypatch.setattr(auth, "email_enabled", lambda: False)
    monkeypatch.setattr(auth, "send_emails", lambda emails: pytest.fail("should not send"))
    with caplog.at_level("WARNING", logger="roomsync.auth"):
        auth.deliver_code(world["teacher"], "654321")
    assert "654321" in caplog.text
