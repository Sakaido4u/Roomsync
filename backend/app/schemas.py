"""The exact shapes of requests and replies, matching docs/API_CONTRACT.md.

FastAPI uses these classes to:
- check incoming JSON (missing or wrongly typed fields give 400 invalid_input),
- turn our database rows into the agreed JSON reply,
- show example bodies on the /docs page.
"""

import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator

from app.models import (
    Booking,
    CameraStatus,
    Room,
    RoomType,
    SchoolClass,
    Subject,
    TeachingAssignment,
    User,
)
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


class UserListItem(BaseModel):
    """One person in the user list (endpoint 24)."""

    user_id: int
    college_id: str
    name: str
    role: str
    department: str

    @classmethod
    def of(cls, user: User) -> "UserListItem":
        return cls(user_id=user.id, college_id=user.college_id, name=user.name,
                   role=user.role.value, department=user.department)


class ClassStudent(BaseModel):
    user_id: int
    college_id: str
    name: str
    is_cr: bool


class MyClassOut(BaseModel):
    """A class the caller is class teacher of, with its students (endpoint 25)."""

    class_id: str
    name: str
    department: str
    students: list[ClassStudent]


class ClassOut(BaseModel):
    """A class with its timetable-sheet details (endpoint 28)."""

    class_id: str
    name: str
    department: str
    semester_label: str | None
    home_room_id: str | None
    strength: int | None
    wef_date: dt.date | None
    class_teacher: PersonRef | None

    @classmethod
    def of(cls, school_class: SchoolClass) -> "ClassOut":
        teacher = school_class.class_teacher
        return cls(
            class_id=school_class.class_id, name=school_class.name,
            department=school_class.department, semester_label=school_class.semester_label,
            home_room_id=school_class.home_room_id, strength=school_class.strength,
            wef_date=school_class.wef_date,
            class_teacher=PersonRef(user_id=teacher.id, name=teacher.name) if teacher else None,
        )


# ---------------------------------------------------------------------------
# Periods, subjects and who teaches what (endpoints 26, 27, 29-32)
# ---------------------------------------------------------------------------

class PeriodOut(BaseModel):
    period: str
    label: str
    start: str
    end: str
    bookable: bool


class PeriodsOut(BaseModel):
    days: list[str]
    periods: list[PeriodOut]


SubjectTypeCode = Literal["IPCC", "PCC", "PEC", "OEC", "PROJ"]


class SubjectIn(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {"code": "BCS702", "title": "Parallel Computing", "type": "IPCC",
                        "credits": 4, "department": "CSE"}
        }
    )

    code: str = Field(min_length=1, max_length=20, pattern=r"^[A-Za-z0-9-]+$")
    title: str = Field(min_length=1, max_length=150)
    type: SubjectTypeCode
    credits: int = Field(ge=0, le=30)
    department: str = Field(min_length=1, max_length=20)


class SubjectOut(BaseModel):
    code: str
    title: str
    type: str
    credits: int
    department: str

    @classmethod
    def of(cls, subject: Subject) -> "SubjectOut":
        return cls(code=subject.code, title=subject.title, type=subject.type.value,
                   credits=subject.credits, department=subject.department)


class TeacherRef(BaseModel):
    user_id: int
    college_id: str
    name: str
    initials: str | None


class TeachingIn(BaseModel):
    """Give the teacher as `teacher` (college ID) or `teacher_id`, not both."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {"teacher": "T002", "subject_code": "BCS702", "class_id": "CSE-7A",
                        "batch": None}
        }
    )

    teacher: str | None = Field(default=None, min_length=1)
    teacher_id: int | None = None
    subject_code: str = Field(min_length=1)
    class_id: str = Field(min_length=1)
    batch: str | None = Field(default=None, min_length=1, max_length=10)

    @model_validator(mode="after")
    def _one_teacher(self) -> "TeachingIn":
        if (self.teacher is None) == (self.teacher_id is None):
            raise ValueError("give exactly one of teacher (college ID) or teacher_id")
        return self


class TeachingOut(BaseModel):
    teaching_id: int
    teacher: TeacherRef
    subject: SubjectOut
    class_id: str
    batch: str | None

    @classmethod
    def of(cls, row: TeachingAssignment) -> "TeachingOut":
        t = row.teacher
        return cls(
            teaching_id=row.id,
            teacher=TeacherRef(user_id=t.id, college_id=t.college_id, name=t.name,
                               initials=t.initials),
            subject=SubjectOut.of(row.subject), class_id=row.class_id, batch=row.batch,
        )


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
    # The time: start and end, or one timetable period ("P3") instead.
    start: dt.time | None = None
    end: dt.time | None = None
    period: str | None = Field(default=None, min_length=1, max_length=10)
    # Required, except for an extra class booked by subject_code, where it
    # is filled in as "Extra class: BCS702, CSE-7A" when left out.
    purpose: str | None = Field(default=None, max_length=200)
    class_id: str | None = None
    # One of the booker's own subjects for class_id (see endpoint 30).
    subject_code: str | None = Field(default=None, min_length=1, max_length=20)

    @model_validator(mode="after")
    def _time_and_purpose(self) -> "BookingCreate":
        has_times = self.start is not None or self.end is not None
        if self.period is not None and has_times:
            raise ValueError("give start and end, or a period, not both")
        if self.period is None and (self.start is None or self.end is None):
            raise ValueError("give start and end, or a period")
        if self.subject_code is None and self.purpose is None:
            raise ValueError("purpose is required unless a subject_code is given")
        if self.subject_code is not None and self.class_id is None:
            raise ValueError("class_id is required with subject_code")
        return self


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


class FreeRoomOut(BaseModel):
    """A suggested free room (endpoint 34)."""

    room_id: str
    name: str
    type: str
    capacity: int
    is_home_room: bool


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
    """One weekly slot.

    - Teacher: `teacher_id`, or `teacher` as a college ID ("T002"). Exactly one.
    - Subject: `subject` (a name), `subject_code` ("BCS702"), or both.
      With only a code, the subject's title is used as the name.
    - `room_id` can be left out for activities with no room (Open Elective,
      Major Project): they appear on the timetable but book nothing.
    - `batch` ("A1") for a lab batch; left out for the whole class.
    """

    room_id: str | None = Field(default=None, min_length=1)
    class_id: str = Field(min_length=1)
    teacher_id: int | None = None
    teacher: str | None = Field(default=None, min_length=1)
    subject: str | None = Field(default=None, min_length=1, max_length=100)
    subject_code: str | None = Field(default=None, min_length=1, max_length=20)
    batch: str | None = Field(default=None, min_length=1, max_length=10)
    weekday: Weekday
    start: dt.time
    end: dt.time

    @model_validator(mode="after")
    def _teacher_and_subject(self) -> "TimetableEntryIn":
        if (self.teacher is None) == (self.teacher_id is None):
            raise ValueError("give exactly one of teacher (college ID) or teacher_id")
        if self.subject is None and self.subject_code is None:
            raise ValueError("give subject, subject_code, or both")
        return self


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
# Week view (endpoint 33)
# ---------------------------------------------------------------------------

class LiveOccupancy(BaseModel):
    occupancy: str
    head_count: int | None
    last_reading_at: dt.datetime | None

    @field_serializer("last_reading_at")
    def _last_reading_at(self, value: dt.datetime | None) -> str | None:
        return to_ist(value).isoformat(timespec="seconds") if value else None


class ChangeInfo(BaseModel):
    """What an admin (or the no-show check) changed, for the hover/tap text."""

    action: str             # override / reschedule / remove / release
    reason: str
    by: str | None          # admin's name; null for the automatic no-show release
    details: str | None     # e.g. "A-313 on 23 Oct, 10:00-11:00 (...) -> B-303 on ..."


class WeekEntry(BaseModel):
    """One class or booking inside a grid cell."""

    booking_id: int | None              # null: on the timetable but books no room
    timetable_entry_id: int | None      # null: a one-time reservation
    subject_code: str | None
    title: str                          # subject title, or the purpose
    purpose: str
    teacher: TeacherRef
    class_id: str | None
    batch: str | None
    room_id: str | None
    start: str
    end: str
    booking_status: str
    is_extra: bool                      # one-time reservation, not a timetable class
    change: ChangeInfo | None
    occupancy: LiveOccupancy | None     # only while it is running now


class WeekCell(BaseModel):
    """One cell of the grid: a period, or several merged (a two-period lab)."""

    period: str                 # first period of the cell
    periods: list[str]          # every period it covers, e.g. ["P6", "P7"]
    start: str
    end: str
    bookable: bool              # false for the lunch break
    entries: list[WeekEntry]    # empty list = a free period


class WeekDay(BaseModel):
    date: dt.date
    weekday: str
    cells: list[WeekCell]
    outside_periods: list[WeekEntry]    # bookings that fall outside every period


class WeekSubject(BaseModel):
    """Who the grid is for: exactly one of teacher, class_info, room is set."""

    kind: Literal["teacher", "class", "room"]
    teacher: TeacherRef | None = None
    class_info: ClassOut | None = None
    room: RoomOut | None = None


class WeekOut(BaseModel):
    week_start: dt.date         # the Monday
    week_end: dt.date           # the Saturday
    today: dt.date
    current_period: str | None  # running now ("P3", "lunch"), or null
    view: WeekSubject
    days: list[WeekDay]
    room_occupancy: LiveOccupancy | None    # room view, while the room has a camera


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
