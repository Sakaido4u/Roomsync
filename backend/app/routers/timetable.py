"""Timetable upload (API contract endpoint 19).

An admin uploads the weekly timetable for a semester. Each entry ("CSE-7A,
Computer Networks, CSE-101, Tuesday 14:30-15:30") becomes one Scheduled
booking per week from semester_start to semester_end.

Clash rules we agreed:
- Two entries in the SAME upload that need the same room at the same time:
  neither is saved, and the clash is reported. That is a timetable mistake.
- An entry that clashes with an EXISTING booking on some dates: the free
  weeks are saved, only the clashing dates are skipped, and each one is
  reported (room, date, time, who holds it, why). An admin decides what to move.
- People detected by a camera never block anything; only bookings do.

Entries without a room (Open Elective, Major Project) are saved so they
show on the timetable, but create no bookings and block no room. Every
entry with a subject_code also records who teaches what (teaching.py).

Uploading again for the same semester REPLACES the earlier timetable:
its classes that have not started yet are removed and rebuilt from the new
upload. Past classes stay as history.

As everywhere else, PostgreSQL's no-overlap rule (models.py) is the judge
of "is this slot free?". Each weekly booking is tried inside a savepoint (a
small undo point inside the transaction): if PostgreSQL refuses it, only
that one date is undone and reported; the rest of the upload carries on.
"""

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import invalid_input, not_found
from app.models import (
    Booking,
    BookingSource,
    BookingStatus,
    ChangeLog,
    Notification,
    Role,
    Room,
    SchoolClass,
    Subject,
    TimetableEntry,
    User,
)
from app.routers.bookings import find_clash
from app.routers.teaching import find_teacher, record_teaching
from app.schemas import (
    EntryClash,
    ExistingBooking,
    SkippedDate,
    TimetableEntryIn,
    TimetableIn,
    TimetableOut,
)
from app.security import require_roles
from app.timeutil import combine, now_ist

router = APIRouter(prefix="/api/timetable", tags=["timetable"])

# Index = Python's date.weekday() number, which is what the database stores.
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

# A semester is a few months; this stops a typo like 2062 creating
# thousands of bookings.
MAX_SEMESTER_DAYS = 366


# ---------------------------------------------------------------------------
# Plain helpers (no database), easy to test on their own
# ---------------------------------------------------------------------------

def weekly_dates(first_day: dt.date, last_day: dt.date, weekday: int) -> list[dt.date]:
    """Every date with this weekday from first_day to last_day, both included."""
    day = first_day + dt.timedelta(days=(weekday - first_day.weekday()) % 7)
    dates = []
    while day <= last_day:
        dates.append(day)
        day += dt.timedelta(days=7)
    return dates


def entry_label(entry: TimetableEntryIn) -> str:
    """'CSE-7A Computer Networks', or 'CSE-7A BCS702 A2' with a code and batch."""
    label = f"{entry.class_id} {entry.subject_code or entry.subject.strip()}"
    return f"{label} {entry.batch}" if entry.batch else label


def booking_purpose(entry: TimetableEntryIn, name: str) -> str:
    """'Parallel Computing', or 'BCS702 Parallel Computing (batch A2)'."""
    purpose = f"{entry.subject_code} {name}" if entry.subject_code else name
    return f"{purpose} (batch {entry.batch})" if entry.batch else purpose


def minutes(t: dt.time) -> dt.time:
    """Drop seconds, so 14:30:59 and 14:30 count as the same time."""
    return t.replace(second=0, microsecond=0)


def find_entry_clashes(entries: list[TimetableEntryIn]) -> tuple[list[EntryClash], set[int]]:
    """Entries in this upload that need the same room at the same time.

    Returns the clashes to report and the positions of every clashing entry
    (none of which will be saved). Entries are grouped by room and weekday,
    sorted by start time, and chained together while each one starts before
    the group so far has ended. Back-to-back (14:30 ends, 14:30 starts) is fine.
    """
    groups: dict[tuple[str, str], list[int]] = defaultdict(list)
    for i, entry in enumerate(entries):
        if entry.room_id is not None:  # no room, nothing to clash over
            groups[(entry.room_id, entry.weekday)].append(i)

    clashes: list[EntryClash] = []
    clashing: set[int] = set()

    def report(room_id: str, weekday: str, chain: list[int]) -> None:
        if len(chain) < 2:
            return
        clashing.update(chain)
        clashes.append(EntryClash(
            room_id=room_id,
            weekday=weekday,
            start=min(minutes(entries[i].start) for i in chain).strftime("%H:%M"),
            end=max(minutes(entries[i].end) for i in chain).strftime("%H:%M"),
            entries=[entry_label(entries[i]) for i in chain],
        ))

    for (room_id, weekday), positions in groups.items():
        positions.sort(key=lambda i: (minutes(entries[i].start), minutes(entries[i].end)))
        chain = [positions[0]]
        chain_end = minutes(entries[positions[0]].end)
        for i in positions[1:]:
            if minutes(entries[i].start) < chain_end:
                chain.append(i)
                chain_end = max(chain_end, minutes(entries[i].end))
            else:
                report(room_id, weekday, chain)
                chain = [i]
                chain_end = minutes(entries[i].end)
        report(room_id, weekday, chain)

    clashes.sort(key=lambda c: (c.room_id, WEEKDAYS.index(c.weekday), c.start))
    return clashes, clashing


# ---------------------------------------------------------------------------
# Steps of an upload
# ---------------------------------------------------------------------------

@dataclass
class CheckedEntry:
    """What check_upload worked out for one entry."""

    teacher_id: int
    name: str  # the subject name to show: given, or the subject's title


def check_upload(db: Session, body: TimetableIn) -> list[CheckedEntry]:
    """Refuse the whole upload (nothing saved) if anything in it is wrong.

    Returns, for each entry in order, its teacher's user ID and subject name.
    """
    if body.semester_end < body.semester_start:
        raise invalid_input("semester_end must be on or after semester_start.")
    if (body.semester_end - body.semester_start).days > MAX_SEMESTER_DAYS:
        raise invalid_input("A semester cannot be longer than one year.")

    for n, entry in enumerate(body.entries):
        if minutes(entry.end) <= minutes(entry.start):
            raise invalid_input(f"entries.{n}: end must be after start.")
        if entry.subject is not None and not entry.subject.strip():
            raise invalid_input(f"entries.{n}: subject cannot be empty.")

    room_ids = {e.room_id for e in body.entries if e.room_id is not None}
    found_rooms = set(db.scalars(select(Room.room_id).where(Room.room_id.in_(room_ids))))
    if missing := sorted(room_ids - found_rooms):
        raise not_found(f"Room {missing[0]} does not exist.")

    class_ids = {e.class_id for e in body.entries}
    found_classes = set(db.scalars(
        select(SchoolClass.class_id).where(SchoolClass.class_id.in_(class_ids))
    ))
    if missing := sorted(class_ids - found_classes):
        raise not_found(f"Class {missing[0]} does not exist.")

    codes = {e.subject_code for e in body.entries if e.subject_code is not None}
    subjects = {s.code: s for s in db.scalars(select(Subject).where(Subject.code.in_(codes)))}
    if missing := sorted(codes - set(subjects)):
        raise not_found(f"Subject {missing[0]} does not exist.")

    # A teacher can be given by user ID or college ID; look each one up once.
    teachers: dict[tuple[int | None, str | None], User] = {}
    checked = []
    for entry in body.entries:
        key = (entry.teacher_id, entry.teacher)
        if key not in teachers:
            teachers[key] = find_teacher(db, entry.teacher_id, entry.teacher)
        name = entry.subject.strip() if entry.subject else subjects[entry.subject_code].title
        checked.append(CheckedEntry(teacher_id=teachers[key].id, name=name[:100]))
    return checked


def remove_previous_timetable(db: Session, body: TimetableIn, now: dt.datetime) -> None:
    """Replace the earlier timetable for an overlapping semester.

    Its classes that have not started yet are removed. A class that an admin
    already changed, or that a notification mentions, is marked cancelled
    instead of deleted, so its history stays readable. Past classes stay.
    """
    old_entries = db.scalars(select(TimetableEntry).where(
        TimetableEntry.semester_start <= body.semester_end,
        TimetableEntry.semester_end >= body.semester_start,
    )).all()
    if not old_entries:
        return

    future = db.scalars(select(Booking).where(
        Booking.timetable_entry_id.in_([e.id for e in old_entries]),
        Booking.status == BookingStatus.scheduled,
        Booking.start_at > now,
    )).all()
    ids = [b.id for b in future]
    has_history = set(db.scalars(select(ChangeLog.booking_id).where(
        ChangeLog.booking_id.in_(ids)
    ))) | set(db.scalars(select(ChangeLog.new_booking_id).where(
        ChangeLog.new_booking_id.in_(ids)
    ))) | set(db.scalars(select(Notification.booking_id).where(
        Notification.booking_id.in_(ids)
    )))

    for booking in future:
        if booking.id in has_history:
            booking.status = BookingStatus.cancelled
        else:
            db.delete(booking)
    db.flush()

    # Past bookings keep source "timetable"; their link to the old entry is
    # cleared by the database (ondelete SET NULL).
    for entry in old_entries:
        db.delete(entry)
    db.flush()


def save_entry(db: Session, body: TimetableIn, entry: TimetableEntryIn,
               checked: CheckedEntry, now: dt.datetime) -> tuple[int, list[SkippedDate]]:
    """Save one entry and its weekly bookings. Returns (created, skipped dates)."""
    weekday = WEEKDAYS.index(entry.weekday)
    row = TimetableEntry(
        room_id=entry.room_id,
        class_id=entry.class_id,
        teacher_id=checked.teacher_id,
        subject=checked.name,
        subject_code=entry.subject_code,
        batch=entry.batch,
        weekday=weekday,
        start_time=minutes(entry.start),
        end_time=minutes(entry.end),
        semester_start=body.semester_start,
        semester_end=body.semester_end,
    )
    db.add(row)
    db.flush()
    if entry.subject_code is not None:
        record_teaching(db, checked.teacher_id, entry.subject_code, entry.class_id,
                        entry.batch)
    if entry.room_id is None:
        return 0, []  # shown on the timetable, but books no room

    created = 0
    skipped: list[SkippedDate] = []
    for day in weekly_dates(body.semester_start, body.semester_end, weekday):
        start, end = combine(day, entry.start), combine(day, entry.end)
        if start <= now:
            continue  # only future classes are created
        try:
            with db.begin_nested():
                db.add(Booking(
                    room_id=entry.room_id,
                    user_id=checked.teacher_id,
                    class_id=entry.class_id,
                    start_at=start,
                    end_at=end,
                    purpose=booking_purpose(entry, checked.name),
                    subject_code=entry.subject_code,
                    status=BookingStatus.scheduled,
                    source=BookingSource.timetable,
                    timetable_entry_id=row.id,
                ))
                db.flush()
        except IntegrityError:
            # PostgreSQL refused this week: the room is already booked.
            clash = find_clash(db, entry.room_id, start, end)
            if clash is not None:
                skipped.append(SkippedDate(
                    room_id=entry.room_id,
                    date=day,
                    start=start.strftime("%H:%M"),
                    end=end.strftime("%H:%M"),
                    entry=entry_label(entry),
                    existing_booking=ExistingBooking.of(clash),
                ))
        else:
            created += 1
    return created, skipped


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.post("", response_model=TimetableOut)
def upload_timetable(
    body: TimetableIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(Role.admin)),
) -> TimetableOut:
    """Upload the weekly timetable for a semester (endpoint 19, admin only).

    Replaces any earlier timetable for the same semester. Entries that clash
    with each other are not saved (see `clashes`); weeks that clash with an
    existing booking are skipped (see `skipped_dates`).
    """
    checked = check_upload(db, body)
    clashes, clashing = find_entry_clashes(body.entries)

    now = now_ist()
    remove_previous_timetable(db, body, now)

    created = 0
    skipped: list[SkippedDate] = []
    for i, entry in enumerate(body.entries):
        if i in clashing:
            continue
        entry_created, entry_skipped = save_entry(db, body, entry, checked[i], now)
        created += entry_created
        skipped.extend(entry_skipped)

    # Everything above is one transaction: it is all saved together here.
    db.commit()

    skipped.sort(key=lambda s: (s.date, s.start, s.room_id))
    return TimetableOut(scheduled_bookings_created=created, clashes=clashes,
                        skipped_dates=skipped)
