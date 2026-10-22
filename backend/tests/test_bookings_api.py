"""Reserving, listing and cancelling bookings (contract endpoints 12, 13, 14)."""

import datetime as dt

from app.config import IST
from app.models import Booking, BookingStatus

# Always a future date, so "cannot book in the past" never trips by accident.
DAY = (dt.datetime.now(IST) + dt.timedelta(days=30)).date().isoformat()


def reserve(client, headers, room="CSE-101", start="15:00", end="16:00", day=DAY, **extra):
    body = {"room_id": room, "date": day, "start": start, "end": end,
            "purpose": "Extra class", **extra}
    return client.post("/api/bookings", json=body, headers=headers)


# --- Reserving -------------------------------------------------------------

def test_teacher_reserves_a_free_room(client, login):
    r = reserve(client, login("teacher"), class_id="CSE-7A")
    assert r.status_code == 201, r.text
    b = r.json()
    assert b["booking_status"] == "reserved"
    assert (b["room_id"], b["date"], b["start"], b["end"]) == ("CSE-101", DAY, "15:00", "16:00")
    assert b["class_id"] == "CSE-7A"
    assert b["booked_by"]["name"] == "Prof. A"
    assert b["created_at"].endswith("+05:30")


def test_admin_can_reserve(client, login):
    assert reserve(client, login("admin")).status_code == 201


def test_student_cannot_reserve(client, login):
    r = reserve(client, login("student"))
    assert r.status_code == 403
    assert r.json()["error"] == "forbidden"


def test_must_be_logged_in(client, world):
    r = reserve(client, {})
    assert r.status_code == 401


def test_overlap_gives_conflict_with_popup_details(client, login):
    reserve(client, login("teacher"), start="15:00", end="16:00", purpose="DBMS")
    r = reserve(client, login("teacher2"), start="15:30", end="16:30")
    assert r.status_code == 409
    body = r.json()
    assert body["error"] == "conflict"
    assert body["existing_booking"]["booked_by"]["name"] == "Prof. A"
    assert body["existing_booking"]["start"] == "15:00"
    assert body["existing_booking"]["booking_status"] == "reserved"
    # Free rooms suggested: same type (classroom) first, never the busy room.
    assert [room["room_id"] for room in body["free_rooms"]] == ["CSE-102", "LAB-1"]


def test_busy_rooms_are_not_suggested(client, login):
    reserve(client, login("teacher"), room="CSE-101")
    reserve(client, login("teacher"), room="CSE-102")
    r = reserve(client, login("teacher2"), room="CSE-101")
    assert [room["room_id"] for room in r.json()["free_rooms"]] == ["LAB-1"]


def test_back_to_back_is_allowed(client, login):
    assert reserve(client, login("teacher"), start="15:00", end="16:00").status_code == 201
    assert reserve(client, login("teacher2"), start="16:00", end="17:00").status_code == 201


def test_end_before_start_is_rejected(client, login):
    r = reserve(client, login("teacher"), start="16:00", end="15:00")
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_input"


def test_past_date_is_rejected(client, login):
    r = reserve(client, login("teacher"), day="2020-01-01")
    assert r.status_code == 400


def test_badly_formatted_time_is_rejected(client, login):
    r = reserve(client, login("teacher"), start="3pm")
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_input"


def test_unknown_room_and_class_give_404(client, login):
    assert reserve(client, login("teacher"), room="NOPE").status_code == 404
    assert reserve(client, login("teacher"), class_id="NOPE").status_code == 404


def test_blank_purpose_is_rejected(client, login):
    r = reserve(client, login("teacher"), purpose="   ")
    assert r.status_code == 400


# --- My bookings -------------------------------------------------------------

def test_my_bookings_lists_only_mine_in_time_order(client, login):
    me = login("teacher")
    reserve(client, me, start="16:00", end="17:00")
    reserve(client, me, start="09:00", end="10:00")
    reserve(client, login("teacher2"), room="CSE-102")
    r = client.get("/api/bookings/mine", headers=me)
    assert r.status_code == 200
    assert [b["start"] for b in r.json()] == ["09:00", "16:00"]


def test_my_bookings_date_filter(client, login):
    me = login("teacher")
    reserve(client, me)
    later = (dt.date.fromisoformat(DAY) + dt.timedelta(days=3)).isoformat()
    reserve(client, me, day=later)
    r = client.get(f"/api/bookings/mine?from={DAY}&to={DAY}", headers=me)
    assert [b["date"] for b in r.json()] == [DAY]


# --- Cancelling --------------------------------------------------------------

def test_cancel_own_booking_frees_the_slot(client, login):
    me = login("teacher")
    booking_id = reserve(client, me).json()["booking_id"]
    r = client.delete(f"/api/bookings/{booking_id}", headers=me)
    assert r.status_code == 200
    assert r.json()["booking_status"] == "cancelled"
    # Someone else can now take the same slot.
    assert reserve(client, login("teacher2")).status_code == 201


def test_cannot_cancel_someone_elses_booking(client, login):
    booking_id = reserve(client, login("teacher")).json()["booking_id"]
    r = client.delete(f"/api/bookings/{booking_id}", headers=login("teacher2"))
    assert r.status_code == 403


def test_cannot_cancel_twice(client, login):
    me = login("teacher")
    booking_id = reserve(client, me).json()["booking_id"]
    client.delete(f"/api/bookings/{booking_id}", headers=me)
    assert client.delete(f"/api/bookings/{booking_id}", headers=me).status_code == 400


def test_teacher_cannot_cancel_timetable_class(client, login, db, world):
    start = dt.datetime.fromisoformat(f"{DAY}T10:00").replace(tzinfo=IST)
    timetable_class = Booking(room_id="CSE-101", user_id=world["teacher"].id,
                              start_at=start, end_at=start + dt.timedelta(hours=1),
                              purpose="Networks", status=BookingStatus.scheduled)
    db.add(timetable_class)
    db.commit()
    r = client.delete(f"/api/bookings/{timetable_class.id}", headers=login("teacher"))
    assert r.status_code == 403


def test_cancel_unknown_booking_gives_404(client, login):
    assert client.delete("/api/bookings/9999", headers=login("teacher")).status_code == 404
