"""Granting and removing admin rights (API contract endpoints 5 and 6).

Only the super admin account can do this. Admins are teachers with extra
rights, so only a teacher can be made an admin, and removing the rights
turns them back into a teacher.

The change takes effect immediately: every request reads the caller's role
from the database (see security.require_roles), not from their login token,
so an admin whose rights were removed is refused on their very next request.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import invalid_input, not_found
from app.models import Role, User
from app.schemas import AdminGrantIn, UserOut
from app.security import require_roles

router = APIRouter(prefix="/api/admin/admins", tags=["admin rights"])

super_admin_only = require_roles(Role.super_admin)


def get_user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise not_found(f"User {user_id} does not exist.")
    return user


@router.post("", response_model=UserOut)
def grant_admin(
    body: AdminGrantIn,
    db: Session = Depends(get_db),
    _: User = Depends(super_admin_only),
) -> UserOut:
    """Give a teacher admin rights (endpoint 5, super admin only)."""
    user = get_user(db, body.user_id)
    if user.role == Role.admin:
        raise invalid_input(f"{user.name} is already an admin.")
    if user.role != Role.teacher:
        raise invalid_input("Only teachers can be made admins.")
    if not user.is_active:
        raise invalid_input(f"{user.name}'s account is not active.")
    user.role = Role.admin
    db.commit()
    return UserOut.of(user)


@router.delete("/{user_id}", response_model=UserOut)
def remove_admin(
    user_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(super_admin_only),
) -> UserOut:
    """Remove admin rights; the person becomes a teacher again (endpoint 6)."""
    user = get_user(db, user_id)
    if user.role != Role.admin:
        raise invalid_input(f"{user.name} is not an admin.")
    user.role = Role.teacher
    db.commit()
    return UserOut.of(user)
