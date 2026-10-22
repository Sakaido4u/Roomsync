"""Passwords, login tokens and "who is calling" checks.

How login works:
1. The user sends college ID + password to /api/auth/login.
2. We check the password against its bcrypt hash.
3. If it matches, we hand back a token (a signed piece of text saying
   "this is user 12, valid until 6 pm"). Nobody can forge it without
   JWT_SECRET from .env.
4. The dashboard sends that token with every later request in the header
   "Authorization: Bearer <token>". `get_current_user` reads it and loads
   the user, so every endpoint knows who is calling.
"""

from datetime import datetime, timedelta

import bcrypt
import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import IST, settings
from app.database import get_db
from app.errors import forbidden, not_logged_in
from app.models import Role, User

# bcrypt only looks at the first 72 bytes of a password, so we refuse
# longer ones instead of silently ignoring the end.
MAX_PASSWORD_BYTES = 72
JWT_ALGORITHM = "HS256"


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    data = password.encode("utf-8")
    if len(data) > MAX_PASSWORD_BYTES:
        raise ValueError("Password is too long (maximum 72 bytes).")
    return bcrypt.hashpw(data, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    data = password.encode("utf-8")
    if len(data) > MAX_PASSWORD_BYTES:
        return False
    return bcrypt.checkpw(data, password_hash.encode("utf-8"))


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------

def create_token(user: User) -> str:
    expires = datetime.now(IST) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {"sub": str(user.id), "role": user.role.value, "exp": expires}
    return jwt.encode(payload, settings.jwt_secret, algorithm=JWT_ALGORITHM)


# auto_error=False: we raise our own error in the contract's format instead
# of FastAPI's default. This also adds the "Authorize" button on /docs.
bearer = HTTPBearer(auto_error=False, description="Paste the token from /api/auth/login")


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    """Dependency: the logged-in user, or a 401 error."""
    if credentials is None:
        raise not_logged_in()
    try:
        payload = jwt.decode(
            credentials.credentials, settings.jwt_secret, algorithms=[JWT_ALGORITHM]
        )
        user_id = int(payload["sub"])
    except jwt.ExpiredSignatureError:
        raise not_logged_in("Your login has expired. Please log in again.")
    except (jwt.InvalidTokenError, KeyError, ValueError):
        raise not_logged_in("Invalid login token. Please log in again.")

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise not_logged_in()
    return user


def require_roles(*roles: Role):
    """Dependency factory: only let these roles through, others get 403.

    The role is read from the database on every request (not trusted from
    the token), so removing someone's admin rights takes effect immediately.

    Usage:  user: User = Depends(require_roles(Role.teacher, Role.admin))
    """

    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise forbidden()
        return user

    return checker
