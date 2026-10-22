"""Login endpoints (API contract endpoints 3 and 4).

Endpoints 1 and 2 (emailed setup code) come later with the email step;
until then, use the demo accounts from `python -m app.seed`.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import not_logged_in
from app.models import User
from app.schemas import LoginIn, LoginOut, UserOut
from app.security import create_token, get_current_user, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Same message for a wrong ID and a wrong password, so nobody can use the
# login page to find out which college IDs exist.
BAD_LOGIN = "Wrong college ID or password."


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
