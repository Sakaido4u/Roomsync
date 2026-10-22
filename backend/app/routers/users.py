"""List people (API contract endpoint 24).

Lets the dashboard show names instead of asking for numeric IDs: the super
admin picks a teacher to make an admin, and an admin's timetable file can
name teachers by college ID. Only admins and the super admin can see it.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Role, User
from app.schemas import UserListItem
from app.security import require_roles

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("", response_model=list[UserListItem])
def list_users(
    role: Role | None = Query(None, description="Only this role, e.g. teacher"),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(Role.admin, Role.super_admin)),
) -> list[UserListItem]:
    """Active users, sorted by name (endpoint 24, admins and super admin)."""
    query = select(User).where(User.is_active.is_(True))
    if role is not None:
        query = query.where(User.role == role)
    return [UserListItem.of(u) for u in db.scalars(query.order_by(User.name))]
