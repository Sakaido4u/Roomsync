"""Room endpoints (API contract endpoints 8, 9, 10 and 11).

Endpoint 9 (room status) is what the dashboard's main grid is built on:
for a chosen date and time slot it returns every room with two separate
tags, booking status and occupancy.
"""

import datetime as dt

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import invalid_input, not_found
from app.models import ACTIVE_STATUSES, Booking, Role, Room, RoomType, User
from app.occupancy import latest_readings, to_occupancy
from app.routers.bookings import overlaps
from app.schemas import BookingOut, RoomCreate, RoomOut, RoomStatusOut, SlotBooking
from app.security import get_current_user, require_roles
from app.timeutil import combine, now_ist

router = APIRouter(prefix="/api/rooms", tags=["rooms"])


def filtered_rooms(db: Session, building: str | None, room_type: RoomType | None) -> list[Room]:
    query = select(Room)
    if building:
        query = query.where(Room.building == building)
    if room_type:
        query = query.where(Room.type == room_type)
    return list(db.scalars(query.order_by(Room.building, Room.room_id)).all())


@router.get("", response_model=list[RoomOut])
def list_rooms(
    building: str | None = Query(None, examples=["Main"]),
    room_type: RoomType | None = Query(None, alias="type"),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[RoomOut]:
    """All rooms, optionally filtered by building and type (endpoint 8)."""
    return [RoomOut.of(r) for r in filtered_rooms(db, building, room_type)]


@router.get("/status", response_model=list[RoomStatusOut])
def room_status(
    date: dt.date = Query(..., examples=["2030-01-07"]),
    start: dt.time = Query(..., examples=["15:00"]),
    end: dt.time = Query(..., examples=["16:00"]),
    building: str | None = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[RoomStatusOut]:
    """Every room's booking status and occupancy for one slot (endpoint 9).

    Occupancy comes from the latest camera reading, so it is only filled in
    when the slot includes the current time. For past or future slots it
    is null.
    """
    slot_start, slot_end = combine(date, start), combine(date, end)
    if slot_end <= slot_start:
        raise invalid_input("end must be after start.")

    rooms = filtered_rooms(db, building, None)
    room_ids = [r.room_id for r in rooms]

    # Active bookings that overlap the slot, earliest first, so a room
    # with two bookings in the slot shows the one that starts first.
    bookings = db.scalars(
        select(Booking)
        .where(Booking.room_id.in_(room_ids), overlaps(slot_start, slot_end))
        .order_by(Booking.start_at)
    ).all()
    booking_by_room: dict[str, Booking] = {}
    for b in bookings:
        booking_by_room.setdefault(b.room_id, b)

    now = now_ist()
    is_now = slot_start <= now < slot_end
    readings = latest_readings(db, room_ids) if is_now else {}

    result = []
    for room in rooms:
        booking = booking_by_room.get(room.room_id)
        occ = to_occupancy(readings.get(room.room_id), now) if is_now else None
        result.append(RoomStatusOut(
            room_id=room.room_id,
            name=room.name,
            type=room.type.value,
            booking_status=booking.status.value if booking else "not_booked",
            booking=SlotBooking.of(booking) if booking else None,
            occupancy=occ.occupancy if occ else None,
            head_count=occ.head_count if occ else None,
            last_reading_at=occ.last_reading_at if occ else None,
        ))
    return result


@router.get("/{room_id}/schedule", response_model=list[BookingOut])
def room_schedule(
    room_id: str,
    date: dt.date = Query(..., examples=["2030-01-07"]),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[BookingOut]:
    """One room's active bookings for a day, in time order (endpoint 10).

    Cancelled, released and overridden bookings are left out, since they
    no longer hold the room.
    """
    if db.get(Room, room_id) is None:
        raise not_found(f"Room {room_id} does not exist.")
    day_start = combine(date, dt.time(0, 0))
    day_end = day_start + dt.timedelta(days=1)
    bookings = db.scalars(
        select(Booking)
        .where(
            Booking.room_id == room_id,
            Booking.status.in_(ACTIVE_STATUSES),
            Booking.start_at < day_end,
            Booking.end_at > day_start,
        )
        .order_by(Booking.start_at)
    ).all()
    return [BookingOut.of(b) for b in bookings]


@router.post("", response_model=RoomOut, status_code=201)
def add_room(
    body: RoomCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(Role.admin)),
) -> RoomOut:
    """Add a room (endpoint 11, admins only). The camera address is stored but never sent back."""
    room_id = body.room_id.upper()
    if db.get(Room, room_id) is not None:
        raise invalid_input(f"Room {room_id} already exists.")
    room = Room(
        room_id=room_id,
        name=body.name.strip(),
        type=body.type,
        building=body.building.strip(),
        floor=body.floor,
        capacity=body.capacity,
        department=body.department.strip().upper(),
        camera_stream=(body.camera_stream or "").strip() or None,
    )
    db.add(room)
    db.commit()
    return RoomOut.of(room)
