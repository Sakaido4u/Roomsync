"""Answering a no-show reminder (API contract endpoint 18).

When the no-show check (app/no_show.py) sees nobody in a booked room, the
teacher who booked it and the class CR get a reminder. Either of them can
answer here:
- "keep": the room is still needed; the no-show check leaves it alone.
- "release": free the room now; the other person is told.
"""

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import forbidden, invalid_input, not_found
from app.models import ACTIVE_STATUSES, Booking, User
from app.no_show import release
from app.notify import send_emails
from app.schemas import BookingOut, NoShowResponseIn
from app.security import get_current_user
from app.timeutil import now_ist

router = APIRouter(prefix="/api/bookings", tags=["no-show"])


def can_answer(user: User, booking: Booking) -> bool:
    """Only the teacher who booked it, or the CR of the booking's class."""
    if booking.user_id == user.id:
        return True
    return bool(user.is_cr and booking.class_id and user.class_id == booking.class_id)


@router.post("/{booking_id}/no-show-response", response_model=BookingOut)
def answer_no_show_reminder(
    booking_id: int,
    body: NoShowResponseIn,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> BookingOut:
    """Keep or release a booking after a no-show reminder (endpoint 18)."""
    booking = db.get(Booking, booking_id)
    if booking is None:
        raise not_found(f"Booking {booking_id} does not exist.")
    if not can_answer(user, booking):
        raise forbidden("Only the teacher who booked it or the class CR can answer.")
    if booking.status.value not in ACTIVE_STATUSES:
        raise invalid_input(f"This booking is already {booking.status.value}.")
    if booking.reminder_sent_at is None:
        raise invalid_input("No no-show reminder was sent for this booking.")
    now = now_ist()
    if booking.end_at <= now:
        raise invalid_input("This booking has already ended.")

    if body.action == "keep":
        booking.no_show_kept_at = now
        db.commit()
    else:
        _, emails = release(db, booking, by=user)
        db.commit()
        background.add_task(send_emails, emails)

    db.refresh(booking)
    return BookingOut.of(booking)
