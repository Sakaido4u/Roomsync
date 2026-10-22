"""Admin changes to existing bookings (API contract endpoints 15, 16 and 17).

Once a room is booked, only an admin can change it. Every change:
- needs a reason (blank or missing -> 400 reason_required),
- is written to the change log (who, when, what, why),
- notifies the teacher who booked it and the class CR, in the dashboard
  and by email.
The change, its log entry and the notifications are saved together: if
one fails, none of them is saved.
"""

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import invalid_input, not_found, reason_required
from app.models import (
    ACTIVE_STATUSES,
    Booking,
    BookingStatus,
    ChangeAction,
    ChangeLog,
    NotificationType,
    Role,
    Room,
    SchoolClass,
    User,
)
from app.notify import describe_slot, notify, send_emails
from app.routers.bookings import conflict_error
from app.schemas import (
    BookingChangeOut,
    BookingOut,
    BookingRef,
    OverrideIn,
    OverrideOut,
    ReasonIn,
    RescheduleIn,
)
from app.security import require_roles
from app.timeutil import combine, now_ist

router = APIRouter(prefix="/api/bookings", tags=["admin changes"])

admin_only = require_roles(Role.admin)


def clean_reason(body: ReasonIn) -> str:
    reason = (body.reason or "").strip()
    if not reason:
        raise reason_required()
    return reason


def active_booking(db: Session, booking_id: int) -> Booking:
    """The booking to change: must exist, still hold the room, and not be over."""
    booking = db.get(Booking, booking_id)
    if booking is None:
        raise not_found(f"Booking {booking_id} does not exist.")
    if booking.status.value not in ACTIVE_STATUSES:
        raise invalid_input(f"This booking is already {booking.status.value}.")
    if booking.end_at <= now_ist():
        raise invalid_input("This booking has already ended.")
    return booking


def label(b: Booking) -> str:
    """'CSE-101 on 3 Nov, 15:00-16:00 (Extra class - DBMS)'"""
    return f"{describe_slot(b.room_id, b.start_at, b.end_at)} ({b.purpose})"


@router.post("/{booking_id}/override", response_model=OverrideOut)
def override_booking(
    booking_id: int,
    body: OverrideIn,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    admin: User = Depends(admin_only),
) -> OverrideOut:
    """Take over a booking's room and time for a new purpose (endpoint 15).

    The old booking is marked "overridden" and a new one is made in the
    admin's name for the same room and time.
    """
    reason = clean_reason(body)
    old = active_booking(db, booking_id)
    purpose = body.purpose.strip()
    if not purpose:
        raise invalid_input("purpose cannot be empty.")
    if body.class_id is not None and db.get(SchoolClass, body.class_id) is None:
        raise not_found(f"Class {body.class_id} does not exist.")

    what = label(old)
    old.status = BookingStatus.overridden
    db.flush()  # frees the slot before the new booking takes it

    new = Booking(room_id=old.room_id, user_id=admin.id, class_id=body.class_id,
                  start_at=old.start_at, end_at=old.end_at, purpose=purpose,
                  status=BookingStatus.reserved)
    db.add(new)
    db.flush()  # gives the new booking its id

    db.add(ChangeLog(booking_id=old.id, new_booking_id=new.id, action=ChangeAction.override,
                     done_by=admin.id, reason=reason, details=what))
    notified, emails = notify(
        db, old, admin, NotificationType.booking_overridden,
        teacher_message=f"Your booking of {what} was taken over by {admin.name}. "
                        f"Reason: {reason}",
        cr_message=f"Your class's booking of {what} was taken over by {admin.name}. "
                   f"Reason: {reason}",
    )
    db.commit()
    background.add_task(send_emails, emails)

    return OverrideOut(
        old_booking=BookingRef(booking_id=old.id, booking_status=old.status.value),
        new_booking=BookingRef(booking_id=new.id, booking_status=new.status.value),
        notified=notified,
    )


@router.post("/{booking_id}/reschedule", response_model=BookingChangeOut)
def reschedule_booking(
    booking_id: int,
    body: RescheduleIn,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    admin: User = Depends(admin_only),
) -> BookingChangeOut:
    """Move a booking to another room and/or time (endpoint 16).

    The booking keeps its id and status. If the new slot is taken, the reply
    is the same 409 conflict as when reserving.
    """
    reason = clean_reason(body)
    booking = active_booking(db, booking_id)

    start, end = combine(body.date, body.start), combine(body.date, body.end)
    if end <= start:
        raise invalid_input("end must be after start.")
    if start < now_ist():
        raise invalid_input("A booking cannot be moved into the past.")
    room = db.get(Room, body.room_id)
    if room is None:
        raise not_found(f"Room {body.room_id} does not exist.")
    if (booking.room_id, booking.start_at, booking.end_at) == (room.room_id, start, end):
        raise invalid_input("The new room and time are the same as the current ones.")

    before = label(booking)
    booking.room_id, booking.start_at, booking.end_at = room.room_id, start, end
    after = describe_slot(room.room_id, start, end)

    db.add(ChangeLog(booking_id=booking.id, action=ChangeAction.reschedule, done_by=admin.id,
                     reason=reason, details=f"{before} -> {after}"))
    notified, emails = notify(
        db, booking, admin, NotificationType.booking_rescheduled,
        teacher_message=f"Your booking of {before} was moved to {after} by {admin.name}. "
                        f"Reason: {reason}",
        cr_message=f"Your class's booking of {before} was moved to {after} by {admin.name}. "
                   f"Reason: {reason}",
    )
    try:
        db.commit()
    except IntegrityError:
        # The new slot overlaps another booking: nothing was saved.
        db.rollback()
        raise conflict_error(db, room, start, end, exclude_id=booking_id)
    background.add_task(send_emails, emails)

    db.refresh(booking)
    return BookingChangeOut(**BookingOut.of(booking).model_dump(), notified=notified)


@router.post("/{booking_id}/remove", response_model=BookingChangeOut)
def remove_booking(
    booking_id: int,
    body: ReasonIn,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    admin: User = Depends(admin_only),
) -> BookingChangeOut:
    """Remove a booking, freeing the room (endpoint 17)."""
    reason = clean_reason(body)
    booking = active_booking(db, booking_id)

    what = label(booking)
    booking.status = BookingStatus.cancelled
    db.add(ChangeLog(booking_id=booking.id, action=ChangeAction.remove, done_by=admin.id,
                     reason=reason, details=what))
    notified, emails = notify(
        db, booking, admin, NotificationType.booking_removed,
        teacher_message=f"Your booking of {what} was removed by {admin.name}. Reason: {reason}",
        cr_message=f"Your class's booking of {what} was removed by {admin.name}. "
                   f"Reason: {reason}",
    )
    db.commit()
    background.add_task(send_emails, emails)

    db.refresh(booking)
    return BookingChangeOut(**BookingOut.of(booking).model_dump(), notified=notified)
