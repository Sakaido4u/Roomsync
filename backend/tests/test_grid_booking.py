"""Booking from the timetable grid: periods, subjects and room suggestions
(contract endpoints 12 and 34)."""

import datetime as dt

import pytest
from sqlalchemy import select

from app.config import IST
from app.models import Booking, SchoolClass, Subject, SubjectType, TeachingAssignment

TODAY = dt.datetime.now(IST).date()
# A Monday at least a week away, so every period on it is in the future.
MONDAY = TODAY + dt.timedelta(days=7 + (7 - TODAY.weekday()) % 7)
SUNDAY = MONDAY + dt.timedelta(days=6)


@pytest.fixture()
def teaching(db, world):
    """T1 teaches BCS702 to CSE-7A: 50 students, home room CSE-102."""
    db.add(Subject(code="BCS702", title="Parallel Computing", type=SubjectType.ipcc,
                   credits=4, department="CSE"))
    cls = db.get(SchoolClass, "CSE-7A")
    cls.strength, cls.home_room_id = 50, "CSE-102"
    db.flush()
    db.add(TeachingAssignment(teacher_id=world["teacher"].id, subject_code="BCS702",
                              class_id="CSE-7A"))
    db.commit()


def book(client, headers, **fields):
    body = {"room_id": "CSE-101", "date": MONDAY.isoformat(), **fields}
    return client.post("/api/bookings", json=body, headers=headers)


# --- Booking a period --------------------------------------------------------

def test_book_a_period(client, login):
    r = book(client, login("teacher"), period="P3", purpose="Meeting")
    assert r.status_code == 201, r.text
    assert (r.json()["start"], r.json()["end"]) == ("11:00", "12:00")


def test_book_the_period_after_lunch(client, login):
    r = book(client, login("teacher"), period="P5", purpose="Meeting")
    assert (r.json()["start"], r.json()["end"]) == ("13:45", "14:45")


def test_free_time_booking_still_works(client, login):
    r = book(client, login("teacher"), start="17:10", end="17:40", purpose="Meeting")
    assert r.status_code == 201, r.text


@pytest.mark.parametrize("fields, words", [
    ({"period": "lunch"}, "lunch is not a bookable period"),
    ({"period": "P9"}, "P9 is not a bookable period"),
    ({"period": "P3", "date": SUNDAY.isoformat()}, "Monday to Saturday"),
    ({"period": "P3", "start": "11:00", "end": "12:00"}, "not both"),
    ({"start": "11:00"}, "give start and end, or a period"),
    ({}, "give start and end, or a period"),
])
def test_bad_period_or_times(client, login, fields, words):
    r = book(client, login("teacher"), purpose="Meeting", **fields)
    assert r.status_code == 400, r.text
    assert words in r.json()["message"]


# --- Booking for one of your subjects ----------------------------------------

def test_extra_class_for_own_subject_fills_the_purpose(client, login, teaching, db):
    r = book(client, login("teacher"), period="P2", class_id="CSE-7A", subject_code="BCS702")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["purpose"] == "Extra class: BCS702, CSE-7A"
    assert body["class_id"] == "CSE-7A"
    assert db.get(Booking, body["booking_id"]).subject_code == "BCS702"


def test_own_purpose_is_kept(client, login, teaching):
    r = book(client, login("teacher"), period="P2", class_id="CSE-7A",
             subject_code="BCS702", purpose="BCS702 doubt session")
    assert r.json()["purpose"] == "BCS702 doubt session"


@pytest.mark.parametrize("who", ["teacher2", "admin"])
def test_cannot_book_for_a_subject_you_do_not_teach(client, login, teaching, db, who):
    r = book(client, login(who), period="P2", class_id="CSE-7A", subject_code="BCS702")
    assert r.status_code == 403, r.text
    assert "You do not teach BCS702 to CSE-7A" in r.json()["message"]
    assert db.scalars(select(Booking)).all() == []


def test_subject_for_another_class_is_refused(client, login, teaching, db):
    db.add(SchoolClass(class_id="CSE-7B", name="CSE 7B", department="CSE"))
    db.commit()
    r = book(client, login("teacher"), period="P2", class_id="CSE-7B", subject_code="BCS702")
    assert r.status_code == 403


def test_subject_needs_a_class(client, login, teaching):
    r = book(client, login("teacher"), period="P2", subject_code="BCS702")
    assert r.status_code == 400
    assert "class_id is required" in r.json()["message"]


def test_purpose_needed_without_a_subject(client, login):
    r = book(client, login("teacher"), period="P2")
    assert r.status_code == 400
    assert "purpose is required" in r.json()["message"]


# --- Suggestions in the "already booked" pop-up ------------------------------

def test_conflict_suggests_rooms_for_the_class(client, login, teaching):
    book(client, login("teacher2"), period="P3", purpose="Seminar")
    r = book(client, login("teacher"), period="P3", class_id="CSE-7A", subject_code="BCS702")
    assert r.status_code == 409
    # Home room first; LAB-1 (40 seats) is too small for 50 students.
    assert [f["room_id"] for f in r.json()["free_rooms"]] == ["CSE-102"]


def test_conflict_without_a_class_suggests_as_before(client, login, teaching):
    book(client, login("teacher2"), period="P3", purpose="Seminar")
    r = book(client, login("teacher"), period="P3", purpose="Meeting")
    assert [f["room_id"] for f in r.json()["free_rooms"]] == ["CSE-102", "LAB-1"]


# --- Free rooms (34) -------------------------------------------------------

def free(client, headers, **params):
    return client.get("/api/rooms/free", params={"date": MONDAY.isoformat(), **params},
                      headers=headers)


def test_free_rooms_for_a_class(client, login, teaching):
    r = free(client, login("teacher"), period="P3", class_id="CSE-7A")
    assert r.status_code == 200, r.text
    assert r.json() == [
        {"room_id": "CSE-102", "name": "Classroom 102", "type": "classroom", "capacity": 60,
         "is_home_room": True},
        {"room_id": "CSE-101", "name": "Classroom 101", "type": "classroom", "capacity": 60,
         "is_home_room": False},
    ]


def test_busy_home_room_is_left_out(client, login, teaching):
    book(client, login("teacher2"), room_id="CSE-102", period="P3", purpose="Seminar")
    r = free(client, login("teacher"), period="P3", class_id="CSE-7A")
    assert [f["room_id"] for f in r.json()] == ["CSE-101"]


def test_free_rooms_without_a_class(client, login, teaching):
    book(client, login("teacher2"), period="P3", purpose="Seminar")
    r = free(client, login("student"), start="11:30", end="12:30")
    assert [f["room_id"] for f in r.json()] == ["CSE-102", "LAB-1"]
    assert not any(f["is_home_room"] for f in r.json())


def test_class_without_strength_can_use_any_room(client, login, world):
    r = free(client, login("teacher"), period="P3", class_id="CSE-7A")
    assert [f["room_id"] for f in r.json()] == ["LAB-1", "CSE-101", "CSE-102"]


@pytest.mark.parametrize("params, status", [
    ({}, 400),
    ({"period": "P3", "start": "11:00", "end": "12:00"}, 400),
    ({"start": "12:00", "end": "11:00"}, 400),
    ({"period": "lunch"}, 400),
    ({"period": "P3", "class_id": "CSE-9Z"}, 404),
])
def test_free_rooms_bad_input(client, login, world, params, status):
    assert free(client, login("teacher"), **params).status_code == status
