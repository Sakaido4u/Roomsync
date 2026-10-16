"""Tests for the database-level booking rules.

Run from the backend folder, with the venv active:

    pytest -v

These check the most important promise in the project: PostgreSQL itself
refuses overlapping bookings, even when two requests arrive together.
"""

import threading
from datetime import date, datetime, time

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.config import IST
from app.models import Booking, BookingStatus, Role, Room, RoomType, User

DAY = date(2030, 1, 7)


def at(hh: int, mm: int = 0) -> datetime:
    return datetime.combine(DAY, time(hh, mm), tzinfo=IST)


@pytest.fixture()
def setup(db):
    teacher = User(college_id="T1", name="Teacher One", email="t1@example.com",
                   role=Role.teacher, department="CSE")
    db.add(teacher)
    db.add_all([
        Room(room_id="R1", name="Room 1", type=RoomType.classroom,
             building="Main", capacity=60, department="CSE"),
        Room(room_id="R2", name="Room 2", type=RoomType.classroom,
             building="Main", capacity=60, department="CSE"),
    ])
    db.commit()
    return teacher


def book(db, teacher, room, start, end, status=BookingStatus.reserved):
    b = Booking(room_id=room, user_id=teacher.id, start_at=start, end_at=end,
                purpose="Test", status=status)
    db.add(b)
    db.commit()
    return b


def test_overlapping_booking_is_rejected(db, setup):
    book(db, setup, "R1", at(10), at(11))
    with pytest.raises(IntegrityError, match="ex_bookings_no_overlap"):
        book(db, setup, "R1", at(10, 30), at(11, 30))


def test_booking_inside_another_is_rejected(db, setup):
    book(db, setup, "R1", at(9), at(12))
    with pytest.raises(IntegrityError):
        book(db, setup, "R1", at(10), at(11))


def test_scheduled_class_also_blocks(db, setup):
    book(db, setup, "R1", at(10), at(11), status=BookingStatus.scheduled)
    with pytest.raises(IntegrityError):
        book(db, setup, "R1", at(10), at(11))


def test_back_to_back_bookings_are_allowed(db, setup):
    book(db, setup, "R1", at(10), at(11))
    book(db, setup, "R1", at(11), at(12))  # starts exactly when the first ends


def test_same_time_in_different_rooms_is_allowed(db, setup):
    book(db, setup, "R1", at(10), at(11))
    book(db, setup, "R2", at(10), at(11))


@pytest.mark.parametrize(
    "old_status",
    [BookingStatus.cancelled, BookingStatus.released, BookingStatus.overridden],
)
def test_inactive_bookings_do_not_block(db, setup, old_status):
    book(db, setup, "R1", at(10), at(11), status=old_status)
    book(db, setup, "R1", at(10), at(11))  # slot is free again


def test_end_must_be_after_start(db, setup):
    with pytest.raises(IntegrityError, match="ck_bookings_end_after_start"):
        book(db, setup, "R1", at(11), at(10))


def test_two_simultaneous_bookings_only_one_wins(engine, db, setup):
    """Two teachers submit the same slot at the same moment.

    Teacher A's booking is sent but not yet saved (committed). While it is
    in flight, teacher B sends the same slot from another connection.
    PostgreSQL makes B wait for A; once A saves, B is refused.
    """
    make_session = sessionmaker(bind=engine)
    teacher_b_result = []

    def teacher_b():
        session = make_session()
        try:
            session.add(Booking(room_id="R1", user_id=setup.id, start_at=at(10),
                                end_at=at(11), purpose="B", status=BookingStatus.reserved))
            session.commit()
            teacher_b_result.append("saved")
        except IntegrityError:
            session.rollback()
            teacher_b_result.append("rejected")
        finally:
            session.close()

    session_a = make_session()
    session_a.add(Booking(room_id="R1", user_id=setup.id, start_at=at(10),
                          end_at=at(11), purpose="A", status=BookingStatus.reserved))
    session_a.flush()  # A's booking is sent to the database, not yet saved

    thread_b = threading.Thread(target=teacher_b)
    thread_b.start()
    thread_b.join(timeout=1)
    assert thread_b.is_alive(), "B should be waiting for A, not finished already"

    session_a.commit()  # A saves; B is now refused
    session_a.close()
    thread_b.join(timeout=10)

    assert teacher_b_result == ["rejected"]
    purposes = db.scalars(select(Booking.purpose)).all()
    assert purposes == ["A"]
