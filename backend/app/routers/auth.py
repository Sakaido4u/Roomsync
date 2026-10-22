"""Login endpoints (API contract endpoints 1 to 4).

Accounts come from the college's ID records; nobody signs up. On first
login (or after forgetting a password):
1. The user asks for a setup code (endpoint 1). A random 6-digit code is
   emailed to their college email. It is stored only as a hash, like a
   password, works once, and expires after SETUP_CODE_MINUTES.
2. They send the code with a new password (endpoint 2).

Both endpoints give the same reply whether or not the college ID exists,
so nobody can use them to find out which IDs are real. Each code allows
MAX_CODE_ATTEMPTS wrong guesses before it stops working, so it cannot be
guessed by trying all 1,000,000 values.
"""

import datetime as dt
import logging
import secrets

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import invalid_input, not_logged_in
from app.models import SetupCode, User
from app.notify import Email, email_enabled, send_emails
from app.schemas import LoginIn, LoginOut, MessageOut, RequestSetupIn, SetPasswordIn, UserOut
from app.security import (
    MAX_PASSWORD_BYTES,
    create_token,
    get_current_user,
    hash_password,
    verify_password,
)
from app.timeutil import now_ist

router = APIRouter(prefix="/api/auth", tags=["auth"])
log = logging.getLogger("roomsync.auth")

# Same message for a wrong ID and a wrong password, so nobody can use the
# login page to find out which college IDs exist.
BAD_LOGIN = "Wrong college ID or password."

SETUP_REPLY = "If this ID exists, a setup code has been sent to its college email."
BAD_CODE = "Wrong or expired code. Ask for a new code if needed."
SETUP_CODE_MINUTES = 15
MAX_CODE_ATTEMPTS = 5
# At most one code email per account per minute, so nobody can flood an inbox.
RESEND_AFTER = dt.timedelta(seconds=60)

# Checked against when there is no real code, so a reply for an unknown ID
# takes as long as one for a real ID.
_DUMMY_HASH = hash_password("000000")


@router.post("/login", response_model=LoginOut)
def login(body: LoginIn, db: Session = Depends(get_db)) -> LoginOut:
    """Log in with college ID and password. Returns a token for later requests."""
    user = db.scalar(select(User).where(User.college_id == body.college_id.strip()))
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        raise not_logged_in(BAD_LOGIN)
    return LoginOut(token=create_token(user), user=UserOut.of(user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> UserOut:
    """Details of whoever is logged in."""
    return UserOut.of(user)


def deliver_code(user: User, code: str) -> None:
    """Email the code. Runs after the reply has gone back."""
    if not email_enabled():
        # Development only: without SMTP in .env the code cannot be emailed,
        # so it is shown in the server window instead. Never happens once
        # email is set up.
        log.warning("Email is not set up (SMTP in .env), so the setup code for %s is "
                    "shown here instead: %s", user.college_id, code)
        return
    send_emails([Email(
        to=user.email,
        subject="RoomSync: your setup code",
        body=(f"Your RoomSync setup code is {code}.\n\n"
              f"Enter it with your new password within {SETUP_CODE_MINUTES} minutes. "
              f"It works once.\n\nIf you did not ask for this code, ignore this email."),
    )])


@router.post("/request-setup", response_model=MessageOut)
def request_setup(
    body: RequestSetupIn,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
) -> MessageOut:
    """Email a one-time setup code to this college ID's email (endpoint 1).

    The reply is always the same, whether or not the ID exists.
    """
    code = f"{secrets.randbelow(1_000_000):06d}"
    # Hashed every time, even for unknown IDs, so the reply time gives nothing away.
    code_hash = hash_password(code)
    now = now_ist()

    user = db.scalar(select(User).where(User.college_id == body.college_id.strip()))
    if user is None or not user.is_active:
        return MessageOut(message=SETUP_REPLY)

    sent_recently = db.scalar(select(SetupCode.id).where(
        SetupCode.user_id == user.id, SetupCode.created_at > now - RESEND_AFTER,
    ).limit(1))
    if sent_recently is not None:
        return MessageOut(message=SETUP_REPLY)

    # Only the newest code works: any older unused one is cancelled.
    db.execute(update(SetupCode)
               .where(SetupCode.user_id == user.id, SetupCode.used.is_(False))
               .values(used=True))
    db.add(SetupCode(user_id=user.id, code_hash=code_hash,
                     expires_at=now + dt.timedelta(minutes=SETUP_CODE_MINUTES)))
    db.commit()
    background.add_task(deliver_code, user, code)
    return MessageOut(message=SETUP_REPLY)


@router.post("/set-password", response_model=MessageOut)
def set_password(body: SetPasswordIn, db: Session = Depends(get_db)) -> MessageOut:
    """Set a password using the emailed code (endpoint 2)."""
    # Checked before the code, so a password typo does not use up a guess.
    if len(body.new_password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise invalid_input("new_password is too long (maximum 72 bytes).")

    user = db.scalar(select(User).where(User.college_id == body.college_id.strip()))
    setup = None
    if user is not None and user.is_active:
        # FOR UPDATE: two guesses at the same moment are counted one after the other.
        setup = db.scalar(
            select(SetupCode)
            .where(SetupCode.user_id == user.id, SetupCode.used.is_(False),
                   SetupCode.expires_at > now_ist())
            .order_by(SetupCode.id.desc())
            .limit(1)
            .with_for_update()
        )
    if setup is None:
        verify_password(body.code, _DUMMY_HASH)   # same time as a real check
        raise invalid_input(BAD_CODE)

    if not verify_password(body.code, setup.code_hash):
        setup.attempts += 1
        if setup.attempts >= MAX_CODE_ATTEMPTS:
            setup.used = True
        db.commit()
        raise invalid_input(BAD_CODE)

    user.password_hash = hash_password(body.new_password)
    setup.used = True
    db.commit()
    return MessageOut(message="Password set. You can now log in.")
