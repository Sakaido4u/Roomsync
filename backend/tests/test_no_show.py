"""No-show check and answering the reminder (contract endpoint 18).

The decision tests build bookings and readings in memory and pass in
"now", so every case is checked without waiting real minutes.
"""

import datetime as dt

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app import no_show
from app.config import IST
from app.models import (
    Booking,
    BookingStatus,
    CameraStatus,
    ChangeLog,
    Notification,
    OccupancyReading,
    Room,
    RoomType,
)
from app.no_show import RELEASE, REMIND, decide, run_no_show_check

START = dt.datetime(2026, 11, 3, 15, 0, tzinfo=IST)
END = START + dt.timedelta(hours=1)


def minutes(n: float) -> dt.timedelta:
    return dt.timedelta(minutes=n)


# --- Building blocks -------------------------------------------------------

def readings(start, end, every_seconds=5, people=False, status=CameraStatus.online,
             room_id="CSE-101"):
    """Camera readings every few seconds from start to end, like the camera program."""
    out, t = [], start
    while t <= end:
        out.append(OccupancyReading(room_id=room_id, time=t, people_detected=people,
                                    head_count=3 if people else 0, camera_status=status))
        t += dt.timedelta(seconds=every_seconds)
    return out


def room(camera=True, enabled=True):
    return Room(room_id="CSE-101", name="Classroom 101", type=RoomType.classroom,
                building="Main", capacity=60, department="CSE",
                camera_stream="rtsp://camera/101" if camera else None, no_show_enabled=enabled)


def booking(status=BookingStatus.reserved, start=START, end=END, **extra):
    return Booking(room_id="CSE-101", user_id=1, start_at=start, end_at=end,
                   purpose="Extra class", status=status, **extra)


# --- Deciding when to remind -----------------------------------------------

def test_reminds_after_15_empty_minutes():
    assert decide(booking(), room(), readings(START, START + minutes(15)),
                  START + minutes(15)) == REMIND


def test_no_reminder_before_15_minutes():
    assert decide(booking(), room(), readings(START, START + minutes(14)),
                  START + minutes(14)) is None


def test_no_reminder_if_anyone_was_seen():
    data = (readings(START, START + minutes(5))
            + readings(START + minutes(5, ), START + minutes(5), people=True)
            + readings(START + minutes(5) + dt.timedelta(seconds=5), START + minutes(15)))
    assert decide(booking(), room(), data, START + minutes(15)) is None


@pytest.mark.parametrize("data", [
    [],                                                                     # no readings
    readings(START + minutes(2), START + minutes(15)),                      # started late
    readings(START, START + minutes(13)),                                   # stopped early
    readings(START, START + minutes(6)) + readings(START + minutes(8), START + minutes(15)),
    readings(START, START + minutes(15), status=CameraStatus.offline),      # camera offline
    readings(START, START + minutes(15), every_seconds=90),                 # too far apart
], ids=["none", "late-start", "stopped", "gap", "offline", "sparse"])
def test_unreliable_camera_data_never_triggers(data):
    assert decide(booking(), room(), data, START + minutes(15)) is None


def test_offline_reading_in_the_middle_blocks():
    data = readings(START, START + minutes(15))
    data[50].camera_status = CameraStatus.offline
    data[50].people_detected = None
    assert decide(booking(), room(), data, START + minutes(15)) is None


@pytest.mark.parametrize("r", [room(camera=False), room(enabled=False)],
                         ids=["no-camera", "check-disabled"])
def test_rooms_without_camera_or_with_check_off_are_skipped(r):
    assert decide(booking(), r, readings(START, START + minutes(15)),
                  START + minutes(15)) is None


@pytest.mark.parametrize("status", [BookingStatus.cancelled, BookingStatus.released,
                                    BookingStatus.overridden])
def test_inactive_bookings_are_skipped(status):
    assert decide(booking(status=status), room(), readings(START, START + minutes(15)),
                  START + minutes(15)) is None


def test_scheduled_classes_are_checked_too():
    assert decide(booking(status=BookingStatus.scheduled), room(),
                  readings(START, START + minutes(15)), START + minutes(15)) == REMIND


def test_kept_bookings_are_skipped():
    b = booking(no_show_kept_at=START + minutes(16), reminder_sent_at=START + minutes(15))
    assert decide(b, room(), readings(START, START + minutes(30)), START + minutes(30)) is None


def test_ended_booking_is_skipped():
    short = booking(end=START + minutes(15))
    assert decide(short, room(), readings(START, START + minutes(15)),
                  START + minutes(15)) is None


# --- Deciding when to release ----------------------------------------------

def reminded():
    return booking(reminder_sent_at=START + minutes(15))


def test_releases_10_minutes_after_reminder_if_still_empty():
    assert decide(reminded(), room(), readings(START, START + minutes(25)),
                  START + minutes(25)) == RELEASE


def test_no_release_before_10_minutes():
    assert decide(reminded(), room(), readings(START, START + minutes(24)),
                  START + minutes(24)) is None


def test_no_release_if_people_arrive_after_reminder():
    data = (readings(START, START + minutes(18))
            + readings(START + minutes(18) + dt.timedelta(seconds=5), START + minutes(25),
                       people=True))
    assert decide(reminded(), room(), data, START + minutes(25)) is None


def test_no_release_if_camera_stops_after_reminder():
    assert decide(reminded(), room(), readings(START, START + minutes(20)),
                  START + minutes(25)) is None


# --- The every-minute job, against the test database ------------------------

NOW = dt.datetime.now(IST).replace(second=0, microsecond=0)


@pytest.fixture()
def camera_room(db, world):
    db.get(Room, "CSE-101").camera_stream = "rtsp://camera/101"
    db.commit()


@pytest.fixture()
def cr(db, world):
    world["student"].is_cr = True
    db.commit()
    return world["student"]


@pytest.fixture()
def run(engine):
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def _run(now):
        run_no_show_check(now=now, session_factory=session_factory)

    return _run


@pytest.fixture()
def sent_emails(monkeypatch):
    sent = []
    monkeypatch.setattr(no_show, "send_emails", lambda emails: sent.extend(emails))
    return sent


def add_booking(db, world, started_minutes_ago, **extra):
    b = Booking(room_id="CSE-101", user_id=world["teacher"].id, class_id="CSE-7A",
                start_at=NOW - minutes(started_minutes_ago),
                end_at=NOW - minutes(started_minutes_ago) + dt.timedelta(hours=1),
                purpose="Extra class", status=BookingStatus.reserved, **extra)
    db.add(b)
    db.commit()
    return b


def add_readings(db, start, end, **kwargs):
    db.add_all(readings(start, end, **kwargs))
    db.commit()


def notifications(db, kind=None):
    db.expire_all()
    query = select(Notification).order_by(Notification.id)
    if kind:
        query = query.where(Notification.type == kind)
    return db.scalars(query).all()


def test_job_sends_reminder_to_teacher_and_cr_once(db, world, camera_room, cr, run,
                                                   sent_emails):
    b = add_booking(db, world, started_minutes_ago=15)
    add_readings(db, b.start_at, NOW)

    run(NOW)
    sent = notifications(db, "no_show_reminder")
    assert {n.user_id for n in sent} == {world["teacher"].id, cr.id}
    assert all(n.booking_id == b.id for n in sent)
    teacher_note = next(n for n in sent if n.user_id == world["teacher"].id)
    assert "No one has been detected in CSE-101" in teacher_note.message
    assert "Keep or Release" in teacher_note.message
    assert len(sent_emails) == 2
    db.expire_all()
    assert db.get(Booking, b.id).reminder_sent_at == NOW

    run(NOW + minutes(1))
    assert len(notifications(db, "no_show_reminder")) == 2


def test_job_releases_after_unanswered_reminder(db, world, camera_room, cr, run, sent_emails):
    b = add_booking(db, world, started_minutes_ago=15)
    add_readings(db, b.start_at, NOW + minutes(10))

    run(NOW)
    run(NOW + minutes(10))

    db.expire_all()
    assert db.get(Booking, b.id).status == BookingStatus.released
    log = db.scalar(select(ChangeLog))
    assert (log.action.value, log.done_by, log.booking_id) == ("release", None, b.id)
    released = notifications(db, "booking_released")
    assert {n.user_id for n in released} == {world["teacher"].id, cr.id}
    assert "was not answered" in released[0].message


def test_released_booking_no_longer_holds_the_room(db, world, camera_room, run, sent_emails):
    b = add_booking(db, world, started_minutes_ago=15)
    add_readings(db, b.start_at, NOW + minutes(10))
    run(NOW)
    run(NOW + minutes(10))
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(Booking).where(
        Booking.status.in_([BookingStatus.reserved, BookingStatus.scheduled]))) == 0


def test_job_does_nothing_without_camera_data(db, world, camera_room, run, sent_emails):
    add_booking(db, world, started_minutes_ago=30)
    run(NOW)
    assert notifications(db) == []


def test_job_skips_room_without_camera(db, world, run, sent_emails):
    b = add_booking(db, world, started_minutes_ago=15)
    add_readings(db, b.start_at, NOW)
    run(NOW)
    assert notifications(db) == []


# --- 18. Answering the reminder ---------------------------------------------

def reminded_booking(db, world):
    """A booking in progress (by real time) whose reminder has gone out."""
    real_now = dt.datetime.now(IST)
    return add_booking(db, world, started_minutes_ago=16,
                       reminder_sent_at=real_now - minutes(1))


def answer(client, headers, booking_id, action):
    return client.post(f"/api/bookings/{booking_id}/no-show-response",
                       json={"action": action}, headers=headers)


def test_teacher_keeps_booking(client, login, db, world, camera_room, run, sent_emails):
    b = reminded_booking(db, world)
    r = answer(client, login("teacher"), b.id, "keep")
    assert r.status_code == 200, r.text
    assert r.json()["booking_status"] == "reserved"
    db.expire_all()
    assert db.get(Booking, b.id).no_show_kept_at is not None

    # Even with an empty room, the check now leaves it alone.
    add_readings(db, b.start_at, NOW + minutes(30))
    run(NOW + minutes(30))
    db.expire_all()
    assert db.get(Booking, b.id).status == BookingStatus.reserved


def test_cr_releases_booking_and_teacher_is_told(client, login, db, world, cr):
    b = reminded_booking(db, world)
    r = answer(client, login("student"), b.id, "release")
    assert r.status_code == 200, r.text
    assert r.json()["booking_status"] == "released"

    log = db.scalar(select(ChangeLog))
    assert (log.action.value, log.done_by) == ("release", cr.id)
    [n] = notifications(db, "booking_released")
    assert n.user_id == world["teacher"].id
    assert "by Student One" in n.message


def test_teacher_releases_and_cr_is_told(client, login, db, world, cr):
    b = reminded_booking(db, world)
    answer(client, login("teacher"), b.id, "release")
    [n] = notifications(db, "booking_released")
    assert n.user_id == cr.id
    assert n.message.startswith("Your class's booking")


@pytest.mark.parametrize("who", ["teacher2", "admin", "student"])
def test_only_booker_or_class_cr_can_answer(client, login, db, world, who):
    b = reminded_booking(db, world)   # the student is not a CR here
    r = answer(client, login(who), b.id, "release")
    assert r.status_code == 403
    db.expire_all()
    assert db.get(Booking, b.id).status == BookingStatus.reserved


def test_cr_of_a_booking_without_class_cannot_answer(client, login, db, world, cr):
    b = reminded_booking(db, world)
    b.class_id = None
    db.commit()
    assert answer(client, login("student"), b.id, "keep").status_code == 403


def test_cannot_answer_without_reminder(client, login, db, world):
    b = add_booking(db, world, started_minutes_ago=5)
    r = answer(client, login("teacher"), b.id, "keep")
    assert r.status_code == 400
    assert "No no-show reminder" in r.json()["message"]


def test_cannot_answer_twice_after_release(client, login, db, world):
    b = reminded_booking(db, world)
    answer(client, login("teacher"), b.id, "release")
    r = answer(client, login("teacher"), b.id, "keep")
    assert r.status_code == 400
    assert "already released" in r.json()["message"]


def test_bad_action(client, login, db, world):
    b = reminded_booking(db, world)
    r = answer(client, login("teacher"), b.id, "maybe")
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_input"


def test_unknown_booking_and_login_needed(client, login, world):
    assert answer(client, login("teacher"), 999, "keep").status_code == 404
    assert answer(client, {}, 999, "keep").status_code == 401
