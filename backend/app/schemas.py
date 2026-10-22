"""The exact shapes of requests and replies, matching docs/API_CONTRACT.md.

FastAPI uses these classes to:
- check incoming JSON (missing or wrongly typed fields give 400 invalid_input),
- turn our database rows into the agreed JSON reply,
- show example bodies on the /docs page.
"""

import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.models import Booking, CameraStatus, Room, RoomType, User
from app.timeutil import hhmm, to_ist


# ---------------------------------------------------------------------------
# Users and login
# ---------------------------------------------------------------------------

class UserOut(BaseModel):
    user_id: int
    college_id: str
    name: str
    email: str
    role: str
    department: str
    class_id: str | None
    is_cr: bool

    @classmethod
    def of(cls, user: User) -> "UserOut":
        return cls(
            user_id=user.id,
            college_id=user.college_id,
            name=user.name,
            email=user.email,
            role=user.role.value,
            department=user.department,
            class_id=user.class_id,
            is_cr=user.is_cr,
        )


class AdminGrantIn(BaseModel):
    """Give a teacher admin rights (endpoint 5)."""

    model_config = ConfigDict(json_schema_extra={"example": {"user_id": 3}})

    user_id: int


class ClassCrIn(BaseModel):
    """Choose the CR of a class (endpoint 7). null clears it."""

    model_config = ConfigDict(json_schema_extra={"example": {"student_id": 5}})

    # Required, but may be null: leaving it out by mistake should not clear the CR.
    student_id: int | None


class LoginIn(BaseModel):
    college_id: str = Field(min_length=1, examples=["T002"])
    password: str = Field(min_length=1, examples=["roomsync123"])


class LoginOut(BaseModel):
    token: str
    user: UserOut


class RequestSetupIn(BaseModel):
    """Ask for a one-time setup code by email (endpoint 1)."""

    model_config = ConfigDict(json_schema_extra={"example": {"college_id": "1JS23CS044"}})

    college_id: str = Field(min_length=1, max_length=30)


class SetPasswordIn(BaseModel):
    """Set a password with the emailed code (endpoint 2)."""

    model_config = ConfigDict(
        json_schema_extra={"example": {"college_id": "1JS23CS044", "code": "483920",
                                       "new_password": "at-least-8-chars"}}
    )

    college_id: str = Field(min_length=1, max_length=30)
    code: str = Field(pattern=r"^\d{6}$")
    new_password: str = Field(min_length=8)


class MessageOut(BaseModel):
    message: str


# ---------------------------------------------------------------------------
# Bookings
# ---------------------------------------------------------------------------

class PersonRef(BaseModel):
    user_id: int
    name: str


class ClassCrOut(BaseModel):
    class_id: str
    cr: PersonRef | None


class BookingOut(BaseModel):
    booking_id: int
    room_id: str
    date: dt.date
    start: str
    end: str
    purpose: str
    class_id: str | None
    booking_status: str
    booked_by: PersonRef
    created_at: dt.datetime

    @field_serializer("created_at")
    def _created_at(self, value: dt.datetime) -> str:
        return to_ist(value).isoformat(timespec="seconds")

    @classmethod
    def of(cls, b: Booking) -> "BookingOut":
        return cls(
            booking_id=b.id,
            room_id=b.room_id,
            date=to_ist(b.start_at).date(),
            start=hhmm(b.start_at),
            end=hhmm(b.end_at),
            purpose=b.purpose,
            class_id=b.class_id,
            booking_status=b.status.value,
            booked_by=PersonRef(user_id=b.booked_by.id, name=b.booked_by.name),
            created_at=b.created_at,
        )


class BookingCreate(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "room_id": "CSE-102",
                "date": "2030-01-07",
                "start": "15:00",
                "end": "16:00",
                "purpose": "Extra class - DBMS",
                "class_id": "CSE-7A",
            }
        }
    )

    room_id: str = Field(min_length=1)
    date: dt.date
    start: dt.time
    end: dt.time
    purpose: str = Field(min_length=1, max_length=200)
    class_id: str | None = None


class ExistingBooking(BaseModel):
    """The booking that is in the way: shown in the "already booked" pop-up
    (endpoint 12's 409 reply) and for each skipped timetable date (endpoint 19)."""

    booking_id: int
    booking_status: str
    booked_by: PersonRef
    purpose: str
    date: dt.date
    start: str
    end: str

    @classmethod
    def of(cls, b: Booking) -> "ExistingBooking":
        full = BookingOut.of(b)
        return cls(booking_id=full.booking_id, booking_status=full.booking_status,
                   booked_by=full.booked_by, purpose=full.purpose, date=full.date,
                   start=full.start, end=full.end)


class RoomRef(BaseModel):
    room_id: str
    name: str


# ---------------------------------------------------------------------------
# Rooms
# ---------------------------------------------------------------------------

ROOM_ID_PATTERN = r"^[A-Za-z0-9-]{2,20}$"


class RoomOut(BaseModel):
    """A room as the dashboard sees it. The camera address is never included."""

    room_id: str
    name: str
    type: str
    building: str
    floor: int
    capacity: int
    department: str
    has_camera: bool

    @classmethod
    def of(cls, room: Room) -> "RoomOut":
        return cls(
            room_id=room.room_id,
            name=room.name,
            type=room.type.value,
            building=room.building,
            floor=room.floor,
            capacity=room.capacity,
            department=room.department,
            has_camera=room.has_camera,
        )


class RoomCreate(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "room_id": "CSE-103",
                "name": "CSE Classroom 103",
                "type": "classroom",
                "building": "Main",
                "floor": 1,
                "capacity": 60,
                "department": "CSE",
                "camera_stream": None,
            }
        }
    )

    room_id: str = Field(pattern=ROOM_ID_PATTERN)
    name: str = Field(min_length=1, max_length=100)
    type: RoomType
    building: str = Field(min_length=1, max_length=50)
    floor: int = Field(0, ge=-2, le=50)
    capacity: int = Field(gt=0, le=1000)
    department: str = Field(min_length=1, max_length=20)
    camera_stream: str | None = Field(None, max_length=500)


class SlotBooking(BaseModel):
    """The booking shown inside a room's status (endpoint 9)."""

    booking_id: int
    booked_by: PersonRef
    purpose: str
    class_id: str | None
    date: dt.date
    start: str
    end: str

    @classmethod
    def of(cls, b: Booking) -> "SlotBooking":
        full = BookingOut.of(b)
        return cls(booking_id=full.booking_id, booked_by=full.booked_by, purpose=full.purpose,
                   class_id=full.class_id, date=full.date, start=full.start, end=full.end)


class RoomStatusOut(BaseModel):
    room_id: str
    name: str
    type: str
    booking_status: str
    booking: SlotBooking | None
    occupancy: str | None
    head_count: int | None
    last_reading_at: dt.datetime | None

    @field_serializer("last_reading_at")
    def _last_reading_at(self, value: dt.datetime | None) -> str | None:
        return to_ist(value).isoformat(timespec="seconds") if value else None


# ---------------------------------------------------------------------------
# Occupancy (camera readings)
# ---------------------------------------------------------------------------

class OccupancyIn(BaseModel):
    """What the camera program sends every few seconds (endpoint 20)."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "room_id": "CSE-101",
                "people_detected": True,
                "head_count": 23,
                "camera_status": "online",
                "time": "2026-11-03T15:04:10+05:30",
            }
        }
    )

    room_id: str = Field(min_length=1)
    people_detected: bool | None
    head_count: int | None = Field(None, ge=0, le=1000)
    camera_status: CameraStatus
    time: dt.datetime


class OccupancyOut(BaseModel):
    """Latest reading for one room (endpoint 21)."""

    room_id: str
    occupancy: str
    head_count: int | None
    last_reading_at: dt.datetime | None

    @field_serializer("last_reading_at")
    def _last_reading_at(self, value: dt.datetime | None) -> str | None:
        return to_ist(value).isoformat(timespec="seconds") if value else None


# ---------------------------------------------------------------------------
# Admin changes to bookings (endpoints 15-17)
# ---------------------------------------------------------------------------

class ReasonIn(BaseModel):
    """Body for removing a booking (endpoint 17)."""

    model_config = ConfigDict(
        json_schema_extra={"example": {"reason": "Department event in this room"}}
    )

    # Optional here so a missing reason gives the contract's
    # "reason_required" error instead of a generic one.
    reason: str | None = Field(None, max_length=500)


class OverrideIn(ReasonIn):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {"purpose": "Placement drive briefing", "class_id": None,
                        "reason": "Company visit moved to today"}
        }
    )

    purpose: str = Field(min_length=1, max_length=200)
    class_id: str | None = None


class RescheduleIn(ReasonIn):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {"room_id": "CSE-102", "date": "2030-01-07", "start": "15:00",
                        "end": "16:00", "reason": "CSE-101 projector under repair"}
        }
    )

    room_id: str = Field(min_length=1)
    date: dt.date
    start: dt.time
    end: dt.time


class NoShowResponseIn(BaseModel):
    """Answer to a no-show reminder (endpoint 18)."""

    model_config = ConfigDict(json_schema_extra={"example": {"action": "keep"}})

    action: Literal["keep", "release"]


class BookingRef(BaseModel):
    booking_id: int
    booking_status: str


class OverrideOut(BaseModel):
    old_booking: BookingRef
    new_booking: BookingRef
    notified: list[str]


class BookingChangeOut(BookingOut):
    """A booking plus who was told about the change (endpoints 16, 17)."""

    notified: list[str]


# ---------------------------------------------------------------------------
# Timetable upload (endpoint 19)
# ---------------------------------------------------------------------------

Weekday = Literal["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


class TimetableEntryIn(BaseModel):
    room_id: str = Field(min_length=1)
    class_id: str = Field(min_length=1)
    teacher_id: int
    subject: str = Field(min_length=1, max_length=100)
    weekday: Weekday
    start: dt.time
    end: dt.time


class TimetableIn(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "semester_start": "2026-08-18",
                "semester_end": "2026-12-05",
                "entries": [
                    {"room_id": "CSE-101", "class_id": "CSE-7A", "teacher_id": 3,
                     "subject": "Computer Networks", "weekday": "tuesday",
                     "start": "14:30", "end": "15:30"}
                ],
            }
        }
    )

    semester_start: dt.date
    semester_end: dt.date
    # A college timetable is a few hundred entries at most.
    entries: list[TimetableEntryIn] = Field(min_length=1, max_length=1000)


class EntryClash(BaseModel):
    """Entries in the same upload that need the same room at the same time."""

    room_id: str
    weekday: str
    start: str
    end: str
    entries: list[str]


class SkippedDate(BaseModel):
    """One week of an entry that was not saved because the room was already booked."""

    room_id: str
    date: dt.date
    start: str
    end: str
    entry: str
    existing_booking: ExistingBooking


class TimetableOut(BaseModel):
    scheduled_bookings_created: int
    clashes: list[EntryClash]
    skipped_dates: list[SkippedDate]


# ---------------------------------------------------------------------------
# Notifications (endpoints 22, 23)
# ---------------------------------------------------------------------------

class NotificationOut(BaseModel):
    notification_id: int
    type: str
    message: str
    booking_id: int | None
    read: bool
    created_at: dt.datetime

    @field_serializer("created_at")
    def _created_at(self, value: dt.datetime) -> str:
        return to_ist(value).isoformat(timespec="seconds")


class NotificationReadOut(BaseModel):
    notification_id: int
    read: bool
