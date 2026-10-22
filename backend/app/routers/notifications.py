"""The logged-in user's notifications (API contract endpoints 22 and 23)."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import forbidden, not_found
from app.models import Notification, User
from app.schemas import NotificationOut, NotificationReadOut
from app.security import get_current_user

router = APIRouter(prefix="/api/notifications", tags=["notifications"])

# Enough for the bell menu; older ones stay in the database.
MAX_NOTIFICATIONS = 100


def to_out(n: Notification) -> NotificationOut:
    return NotificationOut(notification_id=n.id, type=n.type.value, message=n.message,
                           booking_id=n.booking_id, read=n.read, created_at=n.created_at)


@router.get("", response_model=list[NotificationOut])
def my_notifications(
    unread: bool = Query(False, description="true = only unread ones"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[NotificationOut]:
    """Your notifications, newest first (endpoint 22)."""
    query = select(Notification).where(Notification.user_id == user.id)
    if unread:
        query = query.where(Notification.read.is_(False))
    rows = db.scalars(
        query.order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(MAX_NOTIFICATIONS)
    ).all()
    return [to_out(n) for n in rows]


@router.post("/{notification_id}/read", response_model=NotificationReadOut)
def mark_read(
    notification_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> NotificationReadOut:
    """Mark one of your notifications as read (endpoint 23)."""
    n = db.get(Notification, notification_id)
    if n is None:
        raise not_found(f"Notification {notification_id} does not exist.")
    if n.user_id != user.id:
        raise forbidden("You can only mark your own notifications.")
    n.read = True
    db.commit()
    return NotificationReadOut(notification_id=n.id, read=True)
