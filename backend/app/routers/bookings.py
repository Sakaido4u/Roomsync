"""Booking endpoints (API contract endpoints 12, 13 and 14).

The overlap check is NOT written here as an if-statement. We simply try to
save the booking, and PostgreSQL's no-overlap rule (see models.py) refuses
it if the slot is taken. That is what makes it safe when two teachers
submit at the same moment: there is only one judge, the database.
"""

import datetime as dt

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import ApiError, forbidden, invalid_input, not_found
from app.models import ACTIVE_STATUSES, Booking, BookingStatus, Role, Room, SchoolClass, User
from app.schemas import BookingCreate, BookingOut, RoomRef
from app.security import get_current_user, require_roles
from app.timeutil import combine, now_ist

router = APIRouter(prefix="/api/bookings", tags=["bookings"])

# How many free rooms to suggest in the "already booked" pop-up.
MAX_SUGGESTIONS = 5


# ---------------------------------------------------------------------------
# Helpers (also used later by the admin override / reschedule endpoints)
# ---------------------------------------------------------------------------

def overlaps(start: dt.datetime, end: dt.datetime):
    """SQL condition: an active booking whose time overlaps [start, end).

    Two time ranges overlap when each one starts before the other ends.
    Back-to-back (one ends at 15:00, the next starts at 15:00) does not count.
    """
    return and_(
        Booking.status.in_(ACTIVE_STATUSES),
        Booking.start_at < end,
        Booking.end_at > start,
    )


def find_clash(db: Session, room_id: str, start: dt.datetime, end: dt.datetime) -> Booking | None:
    return db.scalar(
        select(Booking)
        .where(Booking.room_id == room_id, overlaps(start, end))
        .order_by(Booking.start_at)
        .limit(1)
    )


def free_rooms(db: Session, start: dt.datetime, end: dt.datetime, wanted: Room) -> list[RoomRef]:
    """Rooms with no active booking in the slot; same type as `wanted` first."""
    busy = exists().where(Booking.room_id == Room.room_id, overlaps(start, end))
    rooms = db.scalars(
        select(Room)
        .where(Room.room_id != wanted.room_id, ~busy)
        .order_by((Room.type != wanted.type), Room.room_id)
        .limit(MAX_SUGGESTIONS)
    ).all()
    return [RoomRef(room_id=r.room_id, name=r.name) for r in rooms]


def conflict_error(db: Session, room: Room, start: dt.datetime, end: dt.datetime) -> ApiError:
    """The 409 reply that the dashboard turns into the "already booked" pop-up."""
    clash = find_clash(db, room.room_id, start, end)
    existing = None
    if clash is not None:
        out = BookingOut.of(clash)
        existing = {
            "booking_id": out.booking_id,
            "booking_status": out.booking_status,
            "booked_by": out.booked_by.model_dump(),
            "purpose": out.purpose,
            "date": out.date.isoformat(),
            "start": out.start,
            "end": out.end,
        }
    return ApiError(
        409,
        "conflict",
        "This room is already booked for that time.",
        existing_booking=existing,
        free_rooms=[r.model_dump() for r in free_rooms(db, start, end, room)],
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("", response_model=BookingOut, status_code=201)
def reserve_room(
    body: BookingCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(Role.teacher, Role.admin)),
) -> BookingOut:
    """Reserve a room (endpoint 12). Overlaps get 409 with the clash and free rooms."""
    start = combine(body.date, body.start)
    end = combine(body.date, body.end)
    purpose = body.purpose.strip()

    # Simple checks first, so the database only has to judge overlaps.
    if end <= start:
        raise invalid_input("end must be after start.")
    if start < now_ist():
        raise invalid_input("Bookings cannot start in the past.")
    if not purpose:
        raise invalid_input("purpose cannot be empty.")

    room = db.get(Room, body.room_id)
    if room is None:
        raise not_found(f"Room {body.room_id} does not exist.")
    if body.class_id is not None and db.get(SchoolClass, body.class_id) is None:
        raise not_found(f"Class {body.class_id} does not exist.")

    booking = Booking(
        room_id=room.room_id,
        user_id=user.id,
        class_id=body.class_id,
        start_at=start,
        end_at=end,
        purpose=purpose,
        status=BookingStatus.reserved,
    )
    db.add(booking)
    try:
        db.commit()
    except IntegrityError:
        # PostgreSQL refused it: the slot overlaps an active booking.
        db.rollback()
        raise conflict_error(db, room, start, end)

    db.refresh(booking)
    return BookingOut.of(booking)


@router.get("/mine", response_model=list[BookingOut])
def my_bookings(
    from_: dt.date | None = Query(None, alias="from", description="First day, YYYY-MM-DD"),
    to: dt.date | None = Query(None, description="Last day, YYYY-MM-DD"),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(Role.teacher, Role.admin)),
) -> list[BookingOut]:
    """Bookings made by the logged-in user, in time order (endpoint 13)."""
    query = select(Booking).where(Booking.user_id == user.id)
    if from_ is not None:
        query = query.where(Booking.start_at >= combine(from_, dt.time(0, 0)))
    if to is not None:
        day_after = to + dt.timedelta(days=1)
        query = query.where(Booking.start_at < combine(day_after, dt.time(0, 0)))
    if from_ is not None and to is not None and to < from_:
        raise invalid_input("to must be on or after from.")
    bookings = db.scalars(query.order_by(Booking.start_at)).all()
    return [BookingOut.of(b) for b in bookings]


@router.delete("/{booking_id}", response_model=BookingOut)
def cancel_booking(
    booking_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> BookingOut:
    """Cancel your own reservation (endpoint 14).

    Only the person who made it can cancel. Timetable (Scheduled) classes
    can only be changed by an admin, through the admin endpoints.
    """
    booking = db.get(Booking, booking_id)
    if booking is None:
        raise not_found(f"Booking {booking_id} does not exist.")
    if booking.user_id != user.id:
        raise forbidden("You can only cancel bookings you made.")
    if booking.status == BookingStatus.scheduled:
        raise forbidden("Timetable classes can only be changed by an admin.")
    if booking.status != BookingStatus.reserved:
        raise invalid_input(f"This booking is already {booking.status.value}.")

    booking.status = BookingStatus.cancelled
    db.commit()
    db.refresh(booking)
    return BookingOut.of(booking)
