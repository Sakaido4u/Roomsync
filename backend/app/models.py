"""Database tables.

Each class below is one table in PostgreSQL. The allowed values (roles,
statuses, ...) are the exact codes from docs/API_CONTRACT.md, so what is
stored is what the API sends.

The most important rule lives in the Booking table: an EXCLUDE
constraint that makes PostgreSQL itself refuse two active bookings for
the same room whose times overlap. Because the database enforces it,
two teachers clicking "Reserve" at the same moment can never both win.
"""

import enum
from datetime import date, datetime, time

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Time,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


# ---------------------------------------------------------------------------
# Allowed values (match the "Fixed values" table in the API contract)
# ---------------------------------------------------------------------------

class Role(str, enum.Enum):
    student = "student"
    teacher = "teacher"
    admin = "admin"
    super_admin = "super_admin"


class RoomType(str, enum.Enum):
    classroom = "classroom"
    lab = "lab"
    meeting_room = "meeting_room"


class BookingStatus(str, enum.Enum):
    # "not_booked" is never stored: it just means no active booking exists.
    scheduled = "scheduled"    # regular timetable class
    reserved = "reserved"      # one-time booking (meeting, extra class)
    overridden = "overridden"  # replaced by an admin, with a reason
    released = "released"      # freed by the no-show check
    cancelled = "cancelled"    # cancelled by the teacher or removed by an admin


# Only these statuses hold the room. Overridden, released and cancelled
# bookings stay in the table as history but no longer block anyone.
ACTIVE_STATUSES = ("scheduled", "reserved")


class BookingSource(str, enum.Enum):
    manual = "manual"
    timetable = "timetable"


class CameraStatus(str, enum.Enum):
    online = "online"
    offline = "offline"


class ChangeAction(str, enum.Enum):
    override = "override"
    reschedule = "reschedule"
    remove = "remove"
    release = "release"


class NotificationType(str, enum.Enum):
    booking_overridden = "booking_overridden"
    booking_rescheduled = "booking_rescheduled"
    booking_removed = "booking_removed"
    no_show_reminder = "no_show_reminder"
    booking_released = "booking_released"


def enum_column(enum_cls: type[enum.Enum], name: str) -> Enum:
    """Store an enum as plain text with a CHECK constraint.

    Plain text is easier to read in pgAdmin and easier to change later than
    a PostgreSQL ENUM type; the CHECK still blocks any value not in the list.
    """
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=30,
        values_callable=lambda e: [member.value for member in e],
    )


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------

class SchoolClass(Base):
    """A class/section such as CSE-7A. Needed so a class teacher can pick a CR."""

    __tablename__ = "classes"

    class_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    department: Mapped[str] = mapped_column(String(20))
    # use_alter: classes and users point at each other, so this foreign key
    # is added after both tables exist.
    class_teacher_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", use_alter=True, name="fk_classes_class_teacher")
    )

    class_teacher: Mapped["User | None"] = relationship(foreign_keys=[class_teacher_id])


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    college_id: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(255), unique=True)
    # Empty until the user sets a password with their setup code.
    password_hash: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(enum_column(Role, "user_role"))
    department: Mapped[str] = mapped_column(String(20))
    class_id: Mapped[str | None] = mapped_column(ForeignKey("classes.class_id"))
    is_cr: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    school_class: Mapped[SchoolClass | None] = relationship(foreign_keys=[class_id])

    __table_args__ = (
        # Only students can be CRs.
        CheckConstraint("NOT is_cr OR role = 'student'", name="ck_users_cr_is_student"),
    )


class SetupCode(Base):
    """One-time codes emailed for first login (API contract endpoints 1 and 2)."""

    __tablename__ = "setup_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    # The code is stored hashed, like a password, never in plain text.
    code_hash: Mapped[str] = mapped_column(String(255))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Room(Base):
    __tablename__ = "rooms"

    room_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    type: Mapped[RoomType] = mapped_column(enum_column(RoomType, "room_type"))
    building: Mapped[str] = mapped_column(String(50))
    floor: Mapped[int] = mapped_column(Integer, default=0)
    capacity: Mapped[int] = mapped_column(Integer)
    department: Mapped[str] = mapped_column(String(20))
    # RTSP address of the room's camera. Never sent to the dashboard.
    camera_stream: Mapped[str | None] = mapped_column(String(500))
    # Admins can turn the no-show check off for specific rooms.
    no_show_enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    @property
    def has_camera(self) -> bool:
        return bool(self.camera_stream)


class Booking(Base):
    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(primary_key=True)
    room_id: Mapped[str] = mapped_column(ForeignKey("rooms.room_id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    class_id: Mapped[str | None] = mapped_column(ForeignKey("classes.class_id"))
    # Stored as full date-times (with time zone) so PostgreSQL can compare
    # ranges. The API splits them into date / start / end.
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    purpose: Mapped[str] = mapped_column(String(200))
    status: Mapped[BookingStatus] = mapped_column(
        enum_column(BookingStatus, "booking_status")
    )
    source: Mapped[BookingSource] = mapped_column(
        enum_column(BookingSource, "booking_source"), default=BookingSource.manual
    )
    timetable_entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("timetable_entries.id", ondelete="SET NULL")
    )
    # Set when the no-show reminder goes out, so it is only sent once.
    reminder_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set when the teacher or CR answers the reminder with "keep": the
    # no-show check then leaves this booking alone.
    no_show_kept_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    room: Mapped[Room] = relationship()
    booked_by: Mapped[User] = relationship(foreign_keys=[user_id])

    __table_args__ = (
        CheckConstraint("end_at > start_at", name="ck_bookings_end_after_start"),
        # THE double-booking rule. In plain words: no two rows may have the
        # same room_id AND overlapping time ranges, counting only active
        # bookings. '[)' means the start is included and the end is not,
        # so 10:00-11:00 and 11:00-12:00 do NOT overlap (back-to-back is fine).
        # Needs the btree_gist extension, which init_db.py turns on.
        ExcludeConstraint(
            (text("room_id"), "="),
            (text("tstzrange(start_at, end_at, '[)')"), "&&"),
            name="ex_bookings_no_overlap",
            using="gist",
            where=text("status IN ('scheduled', 'reserved')"),
        ),
        Index("ix_bookings_room_start", "room_id", "start_at"),
        Index("ix_bookings_user", "user_id"),
    )

    # Handy views of start_at / end_at in the API's date and HH:MM format.
    @property
    def date(self) -> date:
        return self.start_at.date()


class TimetableEntry(Base):
    """One weekly class slot. Each entry creates Scheduled bookings for the semester."""

    __tablename__ = "timetable_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    room_id: Mapped[str] = mapped_column(ForeignKey("rooms.room_id"))
    class_id: Mapped[str] = mapped_column(ForeignKey("classes.class_id"))
    teacher_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    subject: Mapped[str] = mapped_column(String(100))
    # 0 = Monday ... 6 = Sunday (same numbering as Python's date.weekday()).
    weekday: Mapped[int] = mapped_column(Integer)
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    semester_start: Mapped[date] = mapped_column(Date)
    semester_end: Mapped[date] = mapped_column(Date)

    __table_args__ = (
        CheckConstraint("weekday BETWEEN 0 AND 6", name="ck_timetable_weekday"),
        CheckConstraint("end_time > start_time", name="ck_timetable_end_after_start"),
        CheckConstraint("semester_end >= semester_start", name="ck_timetable_semester"),
    )


class OccupancyReading(Base):
    """One result from the camera program. Never contains an image."""

    __tablename__ = "occupancy_readings"

    id: Mapped[int] = mapped_column(primary_key=True)
    room_id: Mapped[str] = mapped_column(ForeignKey("rooms.room_id"))
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Both empty when the camera could not be read.
    people_detected: Mapped[bool | None] = mapped_column(Boolean)
    head_count: Mapped[int | None] = mapped_column(Integer)
    camera_status: Mapped[CameraStatus] = mapped_column(
        enum_column(CameraStatus, "camera_status")
    )

    __table_args__ = (
        CheckConstraint("head_count IS NULL OR head_count >= 0", name="ck_occupancy_count"),
        # Makes "latest reading for this room" fast.
        Index("ix_occupancy_room_time", "room_id", text("time DESC")),
    )


class ChangeLog(Base):
    """History of every admin change and every no-show release."""

    __tablename__ = "change_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id"))
    # For an override, the admin's new booking that took the slot.
    new_booking_id: Mapped[int | None] = mapped_column(ForeignKey("bookings.id"))
    action: Mapped[ChangeAction] = mapped_column(enum_column(ChangeAction, "change_action"))
    # Empty for automatic no-show releases (done by the system, not a person).
    done_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str] = mapped_column(Text)
    # What the booking looked like before, e.g. "CSE-101 2026-11-03 15:00-16:00".
    details: Mapped[str | None] = mapped_column(Text)
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    booking_id: Mapped[int | None] = mapped_column(ForeignKey("bookings.id"))
    type: Mapped[NotificationType] = mapped_column(
        enum_column(NotificationType, "notification_type")
    )
    message: Mapped[str] = mapped_column(Text)
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    # Set once the email copy has been sent.
    emailed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (Index("ix_notifications_user_read", "user_id", "read"),)
