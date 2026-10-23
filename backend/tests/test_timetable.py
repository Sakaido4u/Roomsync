"""Timetable upload (contract endpoint 19)."""

import datetime as dt

import pytest
from sqlalchemy import func, select

from app.config import IST
from app.models import (
    Booking,
    BookingSource,
    BookingStatus,
    ChangeAction,
    ChangeLog,
    OccupancyReading,
    CameraStatus,
    TimetableEntry,
)
from app.routers.timetable import weekly_dates
from app.timeutil import combine

TODAY = dt.datetime.now(IST).date()
# A Monday at least 60 days ahead, and a 4-week semester from it, so every
# weekday occurs exactly 4 times and nothing is in the past.
_IN_60_DAYS = TODAY + dt.timedelta(days=60)
SEM_START = _IN_60_DAYS + dt.timedelta(days=(7 - _IN_60_DAYS.weekday()) % 7)
SEM_END = SEM_START + dt.timedelta(days=27)
FIRST_TUESDAY = SEM_START + dt.timedelta(days=1)


def entry(world, room="CSE-101", weekday="tuesday", start="14:30", end="15:30",
          subject="Computer Networks", teacher="teacher", class_id="CSE-7A"):
    return {"room_id": room, "class_id": class_id, "teacher_id": world[teacher].id,
            "subject": subject, "weekday": weekday, "start": start, "end": end}


def upload(client, headers, entries, start=SEM_START, end=SEM_END):
    body = {"semester_start": start.isoformat(), "semester_end": end.isoformat(),
            "entries": entries}
    return client.post("/api/timetable", json=body, headers=headers)


def active_count(db, room=None):
    query = select(func.count()).select_from(Booking).where(
        Booking.status.in_([BookingStatus.scheduled, BookingStatus.reserved]))
    if room:
        query = query.where(Booking.room_id == room)
    db.expire_all()
    return db.scalar(query)


# --- Plain helpers ----------------------------------------------------------

def test_weekly_dates_includes_both_ends():
    monday = dt.date(2026, 11, 2)
    assert weekly_dates(monday, monday + dt.timedelta(days=14), 0) == [
        monday, monday + dt.timedelta(days=7), monday + dt.timedelta(days=14)]


def test_weekly_dates_starts_at_first_matching_weekday():
    wednesday = dt.date(2026, 11, 4)
    assert weekly_dates(wednesday, dt.date(2026, 11, 20), 0) == [
        dt.date(2026, 11, 9), dt.date(2026, 11, 16)]


# --- Creating scheduled bookings -------------------------------------------

def test_each_entry_becomes_one_scheduled_booking_per_week(client, login, world, db):
    r = upload(client, login("admin"), [entry(world)])
    assert r.status_code == 200, r.text
    assert r.json() == {"scheduled_bookings_created": 4, "clashes": [], "skipped_dates": []}

    bookings = db.scalars(select(Booking).order_by(Booking.start_at)).all()
    assert [b.start_at for b in bookings] == [
        combine(FIRST_TUESDAY + dt.timedelta(weeks=w), dt.time(14, 30)) for w in range(4)]
    entry_row = db.scalar(select(TimetableEntry))
    for b in bookings:
        assert b.status == BookingStatus.scheduled
        assert b.source == BookingSource.timetable
        assert b.timetable_entry_id == entry_row.id
        assert (b.room_id, b.class_id, b.purpose) == ("CSE-101", "CSE-7A", "Computer Networks")
        assert b.user_id == world["teacher"].id


def test_scheduled_bookings_show_in_the_teachers_bookings(client, login, world):
    upload(client, login("admin"), [entry(world)])
    mine = client.get("/api/bookings/mine", headers=login("teacher")).json()
    assert len(mine) == 4
    assert {b["booking_status"] for b in mine} == {"scheduled"}


def test_semester_already_started_only_creates_future_classes(client, login, world, db):
    start = TODAY - dt.timedelta(days=21)
    end = TODAY + dt.timedelta(days=21)
    weekday = TODAY.weekday()
    names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    # 00:00-00:30 today has already started, so today is skipped too.
    r = upload(client, login("admin"),
               [entry(world, weekday=names[weekday], start="00:00", end="00:30")],
               start=start, end=end)
    assert r.status_code == 200, r.text
    assert r.json()["scheduled_bookings_created"] == 3   # the next 3 weeks only
    assert db.scalar(select(func.min(Booking.start_at))).date() > TODAY


# --- Clashes inside the same upload ----------------------------------------

def test_clashing_entries_in_same_upload_are_both_left_out(client, login, world, db):
    r = upload(client, login("admin"), [
        entry(world, subject="Networks Lab", start="09:00", end="11:00"),
        entry(world, subject="DBMS Lab", start="10:00", end="12:00", class_id="CSE-7A"),
        entry(world, room="CSE-102"),   # unrelated, still saved
    ])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["scheduled_bookings_created"] == 4
    assert body["clashes"] == [{
        "room_id": "CSE-101", "weekday": "tuesday", "start": "09:00", "end": "12:00",
        "entries": ["CSE-7A Networks Lab", "CSE-7A DBMS Lab"],
    }]
    assert active_count(db, "CSE-101") == 0
    assert active_count(db, "CSE-102") == 4


def test_three_overlapping_entries_are_one_clash(client, login, world):
    r = upload(client, login("admin"), [
        entry(world, subject="A", start="09:00", end="10:00"),
        entry(world, subject="B", start="09:30", end="11:00"),
        entry(world, subject="C", start="10:30", end="11:30"),
    ])
    clashes = r.json()["clashes"]
    assert len(clashes) == 1
    assert clashes[0]["entries"] == ["CSE-7A A", "CSE-7A B", "CSE-7A C"]
    assert (clashes[0]["start"], clashes[0]["end"]) == ("09:00", "11:30")


@pytest.mark.parametrize("second", [
    {"start": "15:30", "end": "16:30"},                    # back-to-back
    {"weekday": "wednesday"},                              # same time, other day
    {"room": "CSE-102"},                                   # same time, other room
])
def test_not_a_clash(client, login, world, second):
    r = upload(client, login("admin"), [entry(world), entry(world, **second)])
    assert r.json()["clashes"] == []
    assert r.json()["scheduled_bookings_created"] == 8


# --- Clashes with existing bookings ----------------------------------------

def test_clash_with_existing_booking_skips_only_that_date(client, login, world, db):
    week2 = FIRST_TUESDAY + dt.timedelta(weeks=1)
    r = client.post("/api/bookings", headers=login("teacher2"), json={
        "room_id": "CSE-101", "date": week2.isoformat(), "start": "15:00", "end": "16:00",
        "purpose": "Department meeting"})
    assert r.status_code == 201, r.text
    existing_id = r.json()["booking_id"]

    r = upload(client, login("admin"), [entry(world)])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["scheduled_bookings_created"] == 3
    assert body["clashes"] == []
    assert body["skipped_dates"] == [{
        "room_id": "CSE-101",
        "date": week2.isoformat(),
        "start": "14:30",
        "end": "15:30",
        "entry": "CSE-7A Computer Networks",
        "existing_booking": {
            "booking_id": existing_id,
            "booking_status": "reserved",
            "booked_by": {"user_id": world["teacher2"].id, "name": "Prof. B"},
            "purpose": "Department meeting",
            "date": week2.isoformat(),
            "start": "15:00",
            "end": "16:00",
        },
    }]
    # The existing booking is untouched.
    assert db.get(Booking, existing_id).status == BookingStatus.reserved


def test_people_detected_by_camera_never_blocks(client, login, world, db):
    db.add(OccupancyReading(room_id="CSE-101", time=dt.datetime.now(IST),
                            people_detected=True, head_count=30,
                            camera_status=CameraStatus.online))
    db.commit()
    r = upload(client, login("admin"), [entry(world)])
    assert r.json()["scheduled_bookings_created"] == 4


# --- Uploading again replaces the earlier timetable ------------------------

def test_reupload_replaces_future_classes(client, login, world, db):
    upload(client, login("admin"), [entry(world, room="CSE-101")])
    r = upload(client, login("admin"), [entry(world, room="CSE-102", weekday="wednesday")])
    assert r.json() == {"scheduled_bookings_created": 4, "clashes": [], "skipped_dates": []}
    assert active_count(db, "CSE-101") == 0
    assert active_count(db, "CSE-102") == 4
    assert db.scalar(select(func.count()).select_from(TimetableEntry)) == 1


def test_uploading_the_same_file_twice_does_not_clash_with_itself(client, login, world, db):
    upload(client, login("admin"), [entry(world)])
    r = upload(client, login("admin"), [entry(world)])
    assert r.json() == {"scheduled_bookings_created": 4, "clashes": [], "skipped_dates": []}
    assert active_count(db) == 4


def test_reupload_keeps_history_of_changed_classes(client, login, world, db):
    upload(client, login("admin"), [entry(world)])
    changed = db.scalar(select(Booking).order_by(Booking.start_at))
    db.add(ChangeLog(booking_id=changed.id, action=ChangeAction.reschedule,
                     done_by=world["admin"].id, reason="Projector repair"))
    db.commit()

    upload(client, login("admin"), [entry(world)])
    db.expire_all()
    kept = db.get(Booking, changed.id)
    assert kept is not None
    assert kept.status == BookingStatus.cancelled
    assert active_count(db) == 4


def test_reupload_leaves_past_classes_alone(client, login, world, db):
    old = TimetableEntry(room_id="CSE-101", class_id="CSE-7A", teacher_id=world["teacher"].id,
                         subject="Old subject", weekday=0, start_time=dt.time(9),
                         end_time=dt.time(10), semester_start=SEM_START - dt.timedelta(days=90),
                         semester_end=SEM_END)
    db.add(old)
    db.flush()
    yesterday = TODAY - dt.timedelta(days=1)
    past = Booking(room_id="CSE-101", user_id=world["teacher"].id, class_id="CSE-7A",
                   start_at=combine(yesterday, dt.time(9)), end_at=combine(yesterday, dt.time(10)),
                   purpose="Old subject", status=BookingStatus.scheduled,
                   source=BookingSource.timetable, timetable_entry_id=old.id)
    db.add(past)
    db.commit()
    old_id, past_id = old.id, past.id

    upload(client, login("admin"), [entry(world)])
    db.expire_all()
    kept = db.get(Booking, past_id)
    assert kept.status == BookingStatus.scheduled
    assert kept.timetable_entry_id is None
    assert db.get(TimetableEntry, old_id) is None


def test_other_semesters_are_not_replaced(client, login, world, db):
    upload(client, login("admin"), [entry(world)])
    next_start = SEM_END + dt.timedelta(days=1)
    upload(client, login("admin"), [entry(world, room="CSE-102")],
           start=next_start, end=next_start + dt.timedelta(days=27))
    assert active_count(db, "CSE-101") == 4
    assert active_count(db, "CSE-102") == 4


# --- Who can upload ---------------------------------------------------------

@pytest.mark.parametrize("who", ["teacher", "student", "super_admin"])
def test_only_admins_can_upload(client, login, world, db, who):
    r = upload(client, login(who), [entry(world)])
    assert r.status_code == 403
    assert r.json()["error"] == "forbidden"
    assert active_count(db) == 0


def test_upload_needs_login(client, world):
    r = upload(client, {}, [entry(world)])
    assert r.status_code == 401


# --- Bad uploads: nothing is saved -----------------------------------------

@pytest.mark.parametrize("change, status, message", [
    ({"end": "14:00"}, 400, "end must be after start"),
    ({"end": "14:30"}, 400, "end must be after start"),
    ({"weekday": "funday"}, 400, "weekday"),
    ({"subject": "   "}, 400, "subject cannot be empty"),
    ({"room": "NOPE-1"}, 404, "Room NOPE-1 does not exist"),
    ({"class_id": "NOPE-9Z"}, 404, "Class NOPE-9Z does not exist"),
    ({"teacher": "student"}, 400, "is not an active teacher"),
])
def test_bad_entry_rejects_whole_upload(client, login, world, db, change, status, message):
    r = upload(client, login("admin"), [entry(world, room="CSE-102"), entry(world, **change)])
    assert r.status_code == status, r.text
    assert message in r.json()["message"]
    assert active_count(db) == 0
    assert db.scalar(select(func.count()).select_from(TimetableEntry)) == 0


def test_unknown_teacher_id(client, login, world, db):
    bad = entry(world)
    bad["teacher_id"] = 99999
    r = upload(client, login("admin"), [bad])
    assert r.status_code == 404
    assert "User 99999 does not exist" in r.json()["message"]


@pytest.mark.parametrize("start, end, message", [
    (SEM_END, SEM_START, "semester_end must be on or after semester_start"),
    (SEM_START, SEM_START + dt.timedelta(days=400), "longer than one year"),
])
def test_bad_semester_dates(client, login, world, start, end, message):
    r = upload(client, login("admin"), [entry(world)], start=start, end=end)
    assert r.status_code == 400
    assert message in r.json()["message"]


def test_empty_upload_is_refused(client, login, world):
    r = upload(client, login("admin"), [])
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_input"


def test_bad_upload_does_not_remove_previous_timetable(client, login, world, db):
    upload(client, login("admin"), [entry(world)])
    upload(client, login("admin"), [entry(world, room="NOPE-1")])
    assert active_count(db) == 4


# --- Subject codes, batches, no-room entries, teachers by college ID --------

@pytest.fixture()
def subjects(db, world):
    from app.models import Subject, SubjectType
    db.add_all([
        Subject(code="BCS702", title="Parallel Computing", type=SubjectType.ipcc,
                credits=4, department="CSE"),
        Subject(code="OE-7", title="Open Elective", type=SubjectType.oec,
                credits=3, department="CSE"),
    ])
    db.commit()


def coded(world, **fields):
    """An entry given the new way: teacher by college ID, subject by code."""
    e = entry(world, **{k: v for k, v in fields.items() if k in ("room", "weekday", "start",
                                                                 "end", "class_id")})
    del e["teacher_id"], e["subject"]
    e.update({"teacher": "T1", "subject_code": "BCS702"})
    e.update({k: v for k, v in fields.items() if k in ("teacher", "subject_code", "batch",
                                                       "subject")})
    return e


def test_teacher_by_college_id_and_subject_by_code(client, login, world, subjects, db):
    r = upload(client, login("admin"), [coded(world)])
    assert r.status_code == 200, r.text
    assert r.json()["scheduled_bookings_created"] == 4

    row = db.scalar(select(TimetableEntry))
    assert (row.teacher_id, row.subject, row.subject_code, row.batch) == (
        world["teacher"].id, "Parallel Computing", "BCS702", None)
    booking = db.scalar(select(Booking))
    assert booking.purpose == "BCS702 Parallel Computing"
    assert booking.user_id == world["teacher"].id


def test_upload_records_who_teaches_what_once(client, login, world, subjects, db):
    from app.models import TeachingAssignment
    upload(client, login("admin"), [
        coded(world),
        coded(world, weekday="wednesday"),             # same assignment again
        coded(world, weekday="friday", room="LAB-1", batch="A1"),
    ])
    rows = db.scalars(select(TeachingAssignment).order_by(TeachingAssignment.id)).all()
    assert [(a.teacher_id, a.subject_code, a.class_id, a.batch) for a in rows] == [
        (world["teacher"].id, "BCS702", "CSE-7A", None),
        (world["teacher"].id, "BCS702", "CSE-7A", "A1"),
    ]


def test_entry_without_a_room_books_nothing(client, login, world, subjects, db):
    no_room = coded(world, subject_code="OE-7", start="12:00", end="13:00")
    del no_room["room_id"]
    # Another class's open elective at the same time: no room, so no clash.
    other = dict(no_room, teacher="T2")
    r = upload(client, login("admin"), [no_room, other, coded(world)])
    assert r.status_code == 200, r.text
    assert r.json() == {"scheduled_bookings_created": 4, "clashes": [], "skipped_dates": []}

    rows = db.scalars(select(TimetableEntry).order_by(TimetableEntry.id)).all()
    assert [(e.room_id, e.subject) for e in rows] == [
        (None, "Open Elective"), (None, "Open Elective"), ("CSE-101", "Parallel Computing")]
    assert active_count(db) == 4


def test_lab_batches_in_two_rooms_at_the_same_time(client, login, world, subjects, db):
    r = upload(client, login("admin"), [
        coded(world, room="LAB-1", batch="A1", start="14:45", end="16:45"),
        coded(world, room="CSE-102", batch="A2", teacher="T2", start="14:45", end="16:45"),
    ])
    assert r.status_code == 200, r.text
    assert r.json()["scheduled_bookings_created"] == 8
    purposes = set(db.scalars(select(Booking.purpose)))
    assert purposes == {"BCS702 Parallel Computing (batch A1)",
                        "BCS702 Parallel Computing (batch A2)"}


def test_same_room_clash_names_code_and_batch(client, login, world, subjects):
    r = upload(client, login("admin"), [
        coded(world, batch="A1"), coded(world, batch="A2", teacher="T2")])
    assert r.json()["clashes"][0]["entries"] == ["CSE-7A BCS702 A1", "CSE-7A BCS702 A2"]


def test_a_given_subject_name_wins_over_the_title(client, login, world, subjects, db):
    upload(client, login("admin"), [coded(world, subject="Parallel Computing Lab")])
    assert db.scalar(select(TimetableEntry.subject)) == "Parallel Computing Lab"


@pytest.mark.parametrize("change, status, words", [
    ({"subject_code": "NOPE1"}, 404, "Subject NOPE1 does not exist"),
    ({"teacher": "NOBODY"}, 404, "NOBODY does not exist"),
    ({"teacher": "S1"}, 400, "is not an active teacher"),
    ({"teacher_id": 1}, 400, "exactly one of teacher"),
    ({"subject_code": None}, 400, "give subject, subject_code, or both"),
])
def test_bad_new_style_entry_rejects_the_upload(client, login, world, subjects, db,
                                                 change, status, words):
    r = upload(client, login("admin"), [{**coded(world), **change}])
    assert r.status_code == status, r.text
    assert words in r.json()["message"]
    assert db.scalar(select(func.count()).select_from(TimetableEntry)) == 0
