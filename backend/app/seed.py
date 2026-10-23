"""Fill the database with demo data for development and the demo.

Run from the backend folder, with the venv active, on an empty database:

    python -m app.init_db --reset     # type yes
    python -m app.seed

Every demo account has the password  roomsync123  so the team can log in
straight away. Real accounts will use the emailed setup code instead. If
users already exist it does nothing, so running it twice is safe.

What it creates (all names are made up for the demo):
- Semester VII, W.E.F 20 Jul 2026 to 28 Nov 2026, for classes CSE-7A and CSE-7B.
- The CSE-7A timetable, mirroring the college's real VII-A sheet, and
  three CSE-7B classes for Prof. A. Sharma (T002). They are uploaded with
  the real timetable upload, so they work exactly like an admin's upload.
- Two one-time changes in the current week, so the grid has something to show:
  - an extra class: T002's BCS702 doubt session for CSE-7A, Saturday P2, A-312;
  - T002's next CSE-7B class moved by the HOD (T001) to B-303 because the
    A-313 projector is under repair, made with the real reschedule, so
    T002 also gets the notification.
- Mon P7 and Sat P1 stay free in A-312, for booking live in the demo.
- CSE-101 keeps the camera (the phone app's default room) and MR-1 stays.
"""

import datetime as dt

from fastapi import BackgroundTasks
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.init_db import create_tables
from app.models import (
    Booking,
    BookingSource,
    BookingStatus,
    Role,
    Room,
    RoomType,
    SchoolClass,
    Subject,
    SubjectType,
    User,
)
from app.periods import get_period
from app.routers.booking_changes import reschedule_booking
from app.routers.timetable import upload_timetable
from app.schemas import RescheduleIn, TimetableIn
from app.security import hash_password
from app.timeutil import combine, now_ist

DEMO_PASSWORD = "roomsync123"
SEMESTER_START = dt.date(2026, 7, 20)
SEMESTER_END = dt.date(2026, 11, 28)

# (college ID, name, initials, role, class, is CR)
PEOPLE = [
    ("SA001", "Principal's Office", None, Role.super_admin, None, False),
    ("T001", "Dr. K. Rao (HOD)", "KRA", Role.admin, None, False),
    ("T002", "Prof. A. Sharma", "AS", Role.teacher, None, False),
    ("T003", "Prof. R. Rao", "RR", Role.teacher, None, False),
    ("T004", "Dr. K. Rajan", "KR", Role.teacher, None, False),
    ("T005", "Mrs. S. Bhat", "SB", Role.teacher, None, False),
    ("1JS23CS044", "Deeptanshu Pandey", None, Role.student, "CSE-7A", True),
    ("1JS23CS039", "Chirag S", None, Role.student, "CSE-7A", False),
]

# (room ID, name, type, building, floor, capacity, camera)
ROOMS = [
    ("A-312", "Classroom A-312", RoomType.classroom, "A", 3, 70, None),
    ("A-313", "Classroom A-313", RoomType.classroom, "A", 3, 70, None),
    ("A-310", "Lab A-310", RoomType.lab, "A", 3, 36, None),
    ("A-219", "Lab A-219", RoomType.lab, "A", 2, 36, None),
    ("A-202", "Lab A-202", RoomType.lab, "A", 2, 36, None),
    ("B-303", "Classroom B-303", RoomType.classroom, "B", 3, 60, None),
    ("B-304", "Classroom B-304", RoomType.classroom, "B", 3, 60, None),
    ("B-305", "Classroom B-305", RoomType.classroom, "B", 3, 60, None),
    ("B-309", "Classroom B-309", RoomType.classroom, "B", 3, 60, None),
    # CSE-101 is the room the phone camera (RoomSyncMobile) watches by
    # default, so the no-show check runs for it.
    ("CSE-101", "CSE Classroom 101", RoomType.classroom, "Main", 1, 60,
     "phone://RoomSyncMobile"),
    ("MR-1", "Meeting Room 1", RoomType.meeting_room, "Admin", 0, 12, None),
]

# (code, title, type, credits), from the VII-sem course list.
SUBJECTS = [
    ("BCS701", "Internet of Things", SubjectType.ipcc, 4),
    ("BCS702", "Parallel Computing", SubjectType.ipcc, 4),
    ("BCS703", "Cryptography & Network Security", SubjectType.pcc, 4),
    ("BCS714D", "Big Data Analytics (Professional Elective)", SubjectType.pec, 3),
    ("OE-7", "Open Elective (BCV755A / BEC755A / BEI755A)", SubjectType.oec, 3),
    ("BCS786", "Major Project Phase-II", SubjectType.proj, 6),
]

# The CSE-7A sheet: (day, first period, last period, code, teacher, room, batch).
# Room None = the class's home room A-312, except "-" = no room at all.
# The Open Elective is taught by other departments and the Major Project
# by many guides, so the HOD (T001) is listed as their coordinator.
CSE_7A = [
    ("monday", "P1", "P1", "BCS702", "T002", None, None),
    ("monday", "P2", "P2", "BCS701", "T004", None, None),
    ("monday", "P3", "P3", "BCS714D", "T005", None, None),
    ("monday", "P4", "P4", "OE-7", "T001", "-", None),
    ("monday", "P5", "P5", "BCS703", "T003", None, None),
    ("monday", "P6", "P6", "BCS702", "T002", None, None),
    ("tuesday", "P1", "P1", "BCS701", "T004", None, None),
    ("tuesday", "P2", "P2", "BCS703", "T003", None, None),
    ("tuesday", "P3", "P3", "BCS702", "T002", None, None),
    ("tuesday", "P4", "P4", "OE-7", "T001", "-", None),
    ("tuesday", "P5", "P5", "BCS714D", "T005", None, None),
    ("tuesday", "P6", "P7", "BCS701", "T004", "A-310", "A1"),
    ("tuesday", "P6", "P7", "BCS702", "T002", "A-202", "A2"),
    ("wednesday", "P1", "P2", "BCS701", "T004", "A-310", "A2"),
    ("wednesday", "P1", "P2", "BCS702", "T002", "A-219", "A1"),
    ("wednesday", "P3", "P3", "BCS703", "T003", None, None),
    ("wednesday", "P4", "P4", "OE-7", "T001", "-", None),
    ("wednesday", "P5", "P5", "BCS701", "T004", None, None),
    ("wednesday", "P6", "P6", "BCS703", "T003", None, None),
    ("wednesday", "P7", "P7", "BCS714D", "T005", None, None),
    ("thursday", "P1", "P4", "BCS786", "T001", "-", None),
    ("thursday", "P5", "P7", "BCS786", "T001", "-", None),
    ("friday", "P1", "P4", "BCS786", "T001", "-", None),
    ("friday", "P5", "P7", "BCS786", "T001", "-", None),
]

# T002's CSE-7B classes, in its home room A-313.
CSE_7B = [
    ("monday", "P3", "P3", "BCS702", "T002", None, None),
    ("thursday", "P2", "P2", "BCS702", "T002", None, None),
    ("friday", "P5", "P5", "BCS702", "T002", None, None),
]


def timetable_entries(class_id: str, home_room: str, rows: list) -> list[dict]:
    entries = []
    for day, first, last, code, teacher, room, batch in rows:
        entry = {"class_id": class_id, "teacher": teacher, "subject_code": code,
                 "weekday": day, "start": get_period(first).start.strftime("%H:%M"),
                 "end": get_period(last).end.strftime("%H:%M")}
        if room != "-":
            entry["room_id"] = room or home_room
        if batch:
            entry["batch"] = batch
        entries.append(entry)
    return entries


def seed(db: Session) -> dict[str, User]:
    """Add all demo data to an empty database. Returns the people by college ID."""
    pw = hash_password(DEMO_PASSWORD)

    db.add_all([Room(room_id=r, name=n, type=t, building=b, floor=f, capacity=c,
                     department="CSE" if b != "Admin" else "ADMIN", camera_stream=cam)
                for r, n, t, b, f, c, cam in ROOMS])
    db.add_all([Subject(code=c, title=t, type=k, credits=cr, department="CSE")
                for c, t, k, cr in SUBJECTS])
    db.add_all([
        SchoolClass(class_id="CSE-7A", name="CSE 7th sem A", department="CSE",
                    semester_label="VII-A", home_room_id="A-312", strength=64,
                    wef_date=SEMESTER_START),
        SchoolClass(class_id="CSE-7B", name="CSE 7th sem B", department="CSE",
                    semester_label="VII-B", home_room_id="A-313", strength=62,
                    wef_date=SEMESTER_START),
    ])
    db.flush()

    people = {}
    for college_id, name, initials, role, class_id, is_cr in PEOPLE:
        people[college_id] = User(
            college_id=college_id, name=name, initials=initials,
            email=f"{college_id.lower()}@example.com", password_hash=pw, role=role,
            department="ADMIN" if role == Role.super_admin else "CSE",
            class_id=class_id, is_cr=is_cr)
    db.add_all(people.values())
    db.flush()
    db.get(SchoolClass, "CSE-7A").class_teacher_id = people["T002"].id
    db.get(SchoolClass, "CSE-7B").class_teacher_id = people["T003"].id
    db.commit()

    # The timetable, through the real upload (endpoint 19). It books every
    # class from now to the end of the semester.
    result = upload_timetable(
        TimetableIn(semester_start=SEMESTER_START, semester_end=SEMESTER_END,
                    entries=timetable_entries("CSE-7A", "A-312", CSE_7A)
                    + timetable_entries("CSE-7B", "A-313", CSE_7B)),
        db=db, _=people["T001"])
    if result.clashes or result.skipped_dates:
        raise RuntimeError(f"The demo timetable clashed: {result}")

    now = now_ist()
    monday = now.date() - dt.timedelta(days=now.weekday())

    # Extra class on this week's Saturday, P2. Added directly (not through
    # POST /api/bookings) so it works even when that Saturday has passed.
    p2 = get_period("P2")
    saturday = monday + dt.timedelta(days=5)
    db.add(Booking(room_id="A-312", user_id=people["T002"].id, class_id="CSE-7A",
                   start_at=combine(saturday, p2.start), end_at=combine(saturday, p2.end),
                   purpose="BCS702 doubt session", subject_code="BCS702",
                   status=BookingStatus.reserved, source=BookingSource.manual))
    db.commit()

    # T002's next CSE-7B class (this week if one is still to come), moved
    # by the HOD through the real reschedule (endpoint 16).
    nxt = db.scalar(select(Booking).where(
        Booking.class_id == "CSE-7B", Booking.status == BookingStatus.scheduled,
        Booking.start_at > now).order_by(Booking.start_at).limit(1))
    if nxt is not None:
        reschedule_booking(
            nxt.id,
            RescheduleIn(room_id="B-303", date=nxt.start_at.astimezone(now.tzinfo).date(),
                         start=nxt.start_at.astimezone(now.tzinfo).time(),
                         end=nxt.end_at.astimezone(now.tzinfo).time(),
                         reason="A-313 projector under repair"),
            BackgroundTasks(),  # never run: no demo emails
            db=db, admin=people["T001"])
    return people


def main() -> None:
    create_tables()
    db = SessionLocal()
    try:
        if db.scalar(select(User.id).limit(1)) is not None:
            print("Users already exist; nothing added. "
                  "Use 'python -m app.init_db --reset' first for a clean start.")
            return
        people = seed(db)
        print("Demo data added. Log in with any of these college IDs and "
              f"password '{DEMO_PASSWORD}':")
        for u in people.values():
            extra = " (CR of CSE-7A)" if u.is_cr else ""
            print(f"  {u.college_id:<11} {u.role.value:<12} {u.name}{extra}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
