"""The timetable grid's week view (API contract endpoint 33).

For one teacher, class or room, it returns Monday to Saturday, each day
cut into the periods from app/periods.py. Every cell lists what happens
in it:

- Timetable classes, with their real status FOR THAT DATE: a class an
  admin moved, overrode or removed, or the no-show check released, shows
  what changed and why.
- One-time reservations (extra classes, meetings), marked `is_extra`.
- Timetable entries with no room (Open Elective, Major Project): they
  book nothing, so they come straight from the timetable.

A two-period lab or a whole-morning project is one merged cell, and a
free period is a cell with no entries. The class running right now
carries the room's live people detection.
"""

import datetime as dt
from dataclasses import dataclass

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import invalid_input, not_found
from app.models import (
    ACTIVE_STATUSES,
    Booking,
    BookingSource,
    ChangeLog,
    Room,
    SchoolClass,
    Subject,
    TimetableEntry,
    User,
)
from app.occupancy import Occupancy, latest_readings, to_occupancy
from app.periods import PERIODS, TEACHING_DAYS, WEEKDAY_NAMES, period_at
from app.routers.teaching import find_teacher
from app.schemas import (
    ChangeInfo,
    ClassOut,
    LiveOccupancy,
    RoomOut,
    TeacherRef,
    WeekCell,
    WeekDay,
    WeekEntry,
    WeekOut,
    WeekSubject,
)
from app.security import get_current_user
from app.timeutil import combine, now_ist, to_ist

router = APIRouter(prefix="/api/timetable", tags=["timetable"])


@dataclass
class Placed:
    """An entry with its day and times, before it is put into cells."""

    day: dt.date
    start: dt.time
    end: dt.time
    entry: WeekEntry


# ---------------------------------------------------------------------------
# Plain helpers (no database), easy to test on their own
# ---------------------------------------------------------------------------

def monday_of(day: dt.date) -> dt.date:
    return day - dt.timedelta(days=day.weekday())


def hm(t: dt.time) -> str:
    return t.strftime("%H:%M")


def build_cells(items: list[Placed]) -> tuple[list[WeekCell], list[WeekEntry]]:
    """One day's entries -> its cells in period order, plus any entries
    that fall outside every period (e.g. a 17:30 meeting).

    Neighbouring periods become one cell when an entry runs across both
    (a lab in P6 and P7). The lunch break is never merged with anything.
    """
    covering: list[tuple[Placed, set[int]]] = []
    outside: list[WeekEntry] = []
    for item in items:
        indexes = {i for i, p in enumerate(PERIODS)
                   if p.bookable and p.start < item.end and p.end > item.start}
        if indexes:
            covering.append((item, indexes))
        else:
            outside.append(item.entry)

    # joined[i]: period i and the next one share an entry, so they are one cell.
    joined = [any(i in idx and i + 1 in idx for _, idx in covering)
              for i in range(len(PERIODS))]

    cells = []
    first = 0
    while first < len(PERIODS):
        last = first
        while joined[last]:
            last += 1
        group = set(range(first, last + 1))
        entries = [item.entry for item, idx in covering if idx & group]
        entries.sort(key=lambda e: (e.start, e.batch or "", e.room_id or ""))
        cells.append(WeekCell(
            period=PERIODS[first].code,
            periods=[PERIODS[i].code for i in sorted(group)],
            start=hm(PERIODS[first].start),
            end=hm(PERIODS[last].end),
            bookable=PERIODS[first].bookable,
            entries=entries,
        ))
        first = last + 1
    return cells, outside


def live(occ: Occupancy) -> LiveOccupancy:
    return LiveOccupancy(occupancy=occ.occupancy, head_count=occ.head_count,
                         last_reading_at=occ.last_reading_at)


# ---------------------------------------------------------------------------
# Building the week
# ---------------------------------------------------------------------------

def week_view(db: Session, monday: dt.date, now: dt.datetime, *,
              teacher: User | None = None, school_class: SchoolClass | None = None,
              room: Room | None = None) -> WeekOut:
    """The week starting on `monday` for exactly one of teacher, class or room.

    `now` is passed in (not read from the clock) so tests can choose it.
    """
    days = [monday + dt.timedelta(days=d) for d in TEACHING_DAYS]
    week_from = combine(monday, dt.time(0, 0))
    week_to = week_from + dt.timedelta(days=7)

    # 1. Bookings in this week for the teacher, class or room.
    query = select(Booking).where(Booking.start_at < week_to, Booking.end_at > week_from)
    if teacher is not None:
        query = query.where(Booking.user_id == teacher.id)
    if school_class is not None:
        query = query.where(Booking.class_id == school_class.class_id)
    if room is not None:
        query = query.where(Booking.room_id == room.room_id)
    bookings = db.scalars(query.order_by(Booking.start_at)).all()

    # The latest change to each booking (admin change or no-show release).
    changes: dict[int, ChangeLog] = {}
    for log in db.scalars(select(ChangeLog).where(
            ChangeLog.booking_id.in_([b.id for b in bookings]))
            .order_by(ChangeLog.time, ChangeLog.id)):
        changes[log.booking_id] = log
    # A booking that no longer holds its room only shows when someone
    # changed it. A teacher cancelling their own reservation just frees the period.
    bookings = [b for b in bookings
                if b.status.value in ACTIVE_STATUSES or b.id in changes]

    # 2. Timetable entries running this week for the same teacher/class/room.
    query = select(TimetableEntry).where(TimetableEntry.semester_start <= days[-1],
                                         TimetableEntry.semester_end >= monday)
    if teacher is not None:
        query = query.where(TimetableEntry.teacher_id == teacher.id)
    if school_class is not None:
        query = query.where(TimetableEntry.class_id == school_class.class_id)
    if room is not None:
        query = query.where(TimetableEntry.room_id == room.room_id)
    entries = db.scalars(query).all()

    entry_ids = {e.id for e in entries} | {b.timetable_entry_id for b in bookings
                                           if b.timetable_entry_id is not None}
    entry_by_id = {e.id: e for e in db.scalars(
        select(TimetableEntry).where(TimetableEntry.id.in_(entry_ids)))}
    # Which (entry, date) pairs have a booking, whatever its room, time or
    # status now: those are shown through the booking, not the timetable.
    linked = {(entry_id, to_ist(start).date()) for entry_id, start in db.execute(
        select(Booking.timetable_entry_id, Booking.start_at).where(
            Booking.timetable_entry_id.in_([e.id for e in entries]),
            Booking.start_at >= week_from, Booking.start_at < week_to))}

    # Names and titles, each looked up once.
    user_ids = ({b.user_id for b in bookings} | {e.teacher_id for e in entries}
                | {log.done_by for log in changes.values() if log.done_by is not None})
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_(user_ids)))}
    codes = ({b.subject_code for b in bookings} | {e.subject_code for e in entry_by_id.values()})
    subjects = {s.code: s for s in db.scalars(select(Subject).where(Subject.code.in_(codes)))}

    running_rooms = [b.room_id for b in bookings
                     if b.status.value in ACTIVE_STATUSES and b.start_at <= now < b.end_at]
    readings = latest_readings(db, running_rooms + ([room.room_id] if room else []))

    def teacher_ref(user_id: int) -> TeacherRef:
        u = users[user_id]
        return TeacherRef(user_id=u.id, college_id=u.college_id, name=u.name,
                          initials=u.initials)

    def title(code: str | None, fallback: str) -> str:
        return subjects[code].title if code in subjects else fallback

    placed: list[Placed] = []

    for b in bookings:
        entry = entry_by_id.get(b.timetable_entry_id)
        code = b.subject_code or (entry.subject_code if entry else None)
        start, end = to_ist(b.start_at), to_ist(b.end_at)
        log = changes.get(b.id)
        running = b.status.value in ACTIVE_STATUSES and b.start_at <= now < b.end_at
        placed.append(Placed(start.date(), start.time(),
                             end.time() if end.date() == start.date() else dt.time.max,
                             WeekEntry(
            booking_id=b.id,
            timetable_entry_id=b.timetable_entry_id,
            subject_code=code,
            title=title(code, entry.subject if entry else b.purpose),
            purpose=b.purpose,
            teacher=teacher_ref(b.user_id),
            class_id=b.class_id,
            batch=entry.batch if entry else None,
            room_id=b.room_id,
            start=hm(start.time()),
            end=hm(end.time()),
            booking_status=b.status.value,
            is_extra=b.source == BookingSource.manual,
            change=ChangeInfo(
                action=log.action.value, reason=log.reason, details=log.details,
                by=users[log.done_by].name if log.done_by is not None else None,
            ) if log else None,
            occupancy=live(to_occupancy(readings.get(b.room_id), now)) if running else None,
        )))

    for e in entries:
        day = monday + dt.timedelta(days=e.weekday)
        if e.weekday not in TEACHING_DAYS or not e.semester_start <= day <= e.semester_end:
            continue
        if (e.id, day) in linked:
            continue
        # No booking for this date. Shown from the timetable when it has no
        # room (it never books one), or when it had already started (the
        # upload only books classes that have not started yet). A later date
        # with a room but no booking was skipped or removed, so it is not shown.
        if e.room_id is not None and combine(day, e.start_time) > now:
            continue
        placed.append(Placed(day, e.start_time, e.end_time, WeekEntry(
            booking_id=None,
            timetable_entry_id=e.id,
            subject_code=e.subject_code,
            title=title(e.subject_code, e.subject),
            purpose=e.subject,
            teacher=teacher_ref(e.teacher_id),
            class_id=e.class_id,
            batch=e.batch,
            room_id=e.room_id,
            start=hm(e.start_time),
            end=hm(e.end_time),
            booking_status="scheduled",
            is_extra=False,
            change=None,
            occupancy=None,
        )))

    week_days = []
    for day in days:
        cells, outside = build_cells([p for p in placed if p.day == day])
        week_days.append(WeekDay(date=day, weekday=WEEKDAY_NAMES[day.weekday()],
                                 cells=cells, outside_periods=outside))

    today = now.date()
    current = period_at(now.time()) if today.weekday() in TEACHING_DAYS else None
    if teacher is not None:
        view = WeekSubject(kind="teacher", teacher=TeacherRef(
            user_id=teacher.id, college_id=teacher.college_id, name=teacher.name,
            initials=teacher.initials))
    elif school_class is not None:
        view = WeekSubject(kind="class", class_info=ClassOut.of(school_class))
    else:
        view = WeekSubject(kind="room", room=RoomOut.of(room))
    in_this_week = monday <= today < monday + dt.timedelta(days=7)

    return WeekOut(
        week_start=monday,
        week_end=days[-1],
        today=today,
        current_period=current.code if current else None,
        view=view,
        days=week_days,
        room_occupancy=(live(to_occupancy(readings.get(room.room_id), now))
                        if room is not None and in_this_week else None),
    )


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.get("/week", response_model=WeekOut)
def get_week(
    week_start: dt.date | None = Query(None, description="Any day of the week, YYYY-MM-DD; "
                                       "default this week"),
    teacher: str | None = Query(None, description="A teacher's college ID", examples=["T002"]),
    class_id: str | None = Query(None, examples=["CSE-7A"]),
    room_id: str | None = Query(None, examples=["A-312"]),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> WeekOut:
    """One week of the timetable grid for a teacher, class or room (endpoint 33)."""
    if sum(x is not None for x in (teacher, class_id, room_id)) != 1:
        raise invalid_input("Give exactly one of teacher, class_id or room_id.")
    now = now_ist()
    monday = monday_of(week_start or now.date())

    if teacher is not None:
        return week_view(db, monday, now, teacher=find_teacher(db, college_id=teacher))
    if class_id is not None:
        school_class = db.get(SchoolClass, class_id)
        if school_class is None:
            raise not_found(f"Class {class_id} does not exist.")
        return week_view(db, monday, now, school_class=school_class)
    found = db.get(Room, room_id)
    if found is None:
        raise not_found(f"Room {room_id} does not exist.")
    return week_view(db, monday, now, room=found)
