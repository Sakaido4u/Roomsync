"""Fill the database with demo data for development.

Run from the backend folder, with the venv active:

    python -m app.seed

Every demo account has the password  roomsync123  so the team can log in
straight away while building. Real accounts will use the emailed setup
code instead. Run it once; it does nothing if users already exist.
"""

from datetime import datetime, time, timedelta

from sqlalchemy import select

from app.config import IST
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
    User,
)
from app.security import hash_password

DEMO_PASSWORD = "roomsync123"


def at(day, hh: int, mm: int = 0) -> datetime:
    return datetime.combine(day, time(hh, mm), tzinfo=IST)


def main() -> None:
    create_tables()
    db = SessionLocal()
    try:
        if db.scalar(select(User.id).limit(1)) is not None:
            print("Users already exist; nothing added. "
                  "Use 'python -m app.init_db --reset' first for a clean start.")
            return

        pw = hash_password(DEMO_PASSWORD)

        # Classes first (without class teachers, which are added below).
        cse7a = SchoolClass(class_id="CSE-7A", name="CSE 7th sem A", department="CSE")
        cse5b = SchoolClass(class_id="CSE-5B", name="CSE 5th sem B", department="CSE")
        db.add_all([cse7a, cse5b])
        db.flush()

        super_admin = User(college_id="SA001", name="Principal's Office",
                           email="sa001@example.com", password_hash=pw,
                           role=Role.super_admin, department="ADMIN")
        hod = User(college_id="T001", name="Dr. K. Rao (HOD)",
                   email="t001@example.com", password_hash=pw,
                   role=Role.admin, department="CSE")
        sharma = User(college_id="T002", name="Prof. A. Sharma",
                      email="t002@example.com", password_hash=pw,
                      role=Role.teacher, department="CSE")
        rrao = User(college_id="T003", name="Prof. R. Rao",
                    email="t003@example.com", password_hash=pw,
                    role=Role.teacher, department="CSE")
        cr = User(college_id="1JS23CS044", name="Deeptanshu Pandey",
                  email="1js23cs044@example.com", password_hash=pw,
                  role=Role.student, department="CSE", class_id="CSE-7A", is_cr=True)
        student = User(college_id="1JS23CS039", name="Chirag S",
                       email="1js23cs039@example.com", password_hash=pw,
                       role=Role.student, department="CSE", class_id="CSE-7A")
        db.add_all([super_admin, hod, sharma, rrao, cr, student])
        db.flush()

        cse7a.class_teacher_id = sharma.id
        cse5b.class_teacher_id = rrao.id

        db.add_all([
            Room(room_id="CSE-101", name="CSE Classroom 101", type=RoomType.classroom,
                 building="Main", floor=1, capacity=60, department="CSE"),
            Room(room_id="CSE-102", name="CSE Classroom 102", type=RoomType.classroom,
                 building="Main", floor=1, capacity=60, department="CSE"),
            Room(room_id="CSE-LAB2", name="CSE Lab 2", type=RoomType.lab,
                 building="Main", floor=2, capacity=40, department="CSE"),
            Room(room_id="MR-1", name="Meeting Room 1", type=RoomType.meeting_room,
                 building="Admin", floor=0, capacity=12, department="ADMIN"),
        ])
        db.flush()

        # Two bookings for tomorrow so the dashboard has something to show.
        tomorrow = datetime.now(IST).date() + timedelta(days=1)
        db.add_all([
            Booking(room_id="CSE-101", user_id=rrao.id, class_id="CSE-5B",
                    start_at=at(tomorrow, 14, 30), end_at=at(tomorrow, 15, 30),
                    purpose="Computer Networks", status=BookingStatus.scheduled,
                    source=BookingSource.timetable),
            Booking(room_id="MR-1", user_id=sharma.id, class_id=None,
                    start_at=at(tomorrow, 15), end_at=at(tomorrow, 16),
                    purpose="Department meeting", status=BookingStatus.reserved),
        ])

        db.commit()
        print("Demo data added. Log in with any of these college IDs and "
              f"password '{DEMO_PASSWORD}':")
        for u in (super_admin, hod, sharma, rrao, cr, student):
            extra = " (CR)" if u.is_cr else ""
            print(f"  {u.college_id:<11} {u.role.value:<12} {u.name}{extra}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
