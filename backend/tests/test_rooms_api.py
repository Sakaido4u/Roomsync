"""Rooms: list, status grid, schedule and adding rooms (contract endpoints 8-11)."""

import datetime as dt

import pytest

from app.config import IST
from app.models import Booking, BookingStatus, CameraStatus, OccupancyReading

FUTURE = (dt.datetime.now(IST) + dt.timedelta(days=30)).date()


def at(day: dt.date, hh: int, mm: int = 0) -> dt.datetime:
    return dt.datetime.combine(day, dt.time(hh, mm), tzinfo=IST)


def add_booking(db, world, room, start, end, status=BookingStatus.reserved, who="teacher",
                purpose="Class"):
    b = Booking(room_id=room, user_id=world[who].id, start_at=start, end_at=end,
                purpose=purpose, status=status)
    db.add(b)
    db.commit()
    return b


def status_of(client, headers, day, start, end, **params):
    query = {"date": day.isoformat(), "start": start, "end": end, **params}
    r = client.get("/api/rooms/status", params=query, headers=headers)
    assert r.status_code == 200, r.text
    return {room["room_id"]: room for room in r.json()}


# --- 8. List rooms ----------------------------------------------------------

def test_list_rooms(client, login):
    r = client.get("/api/rooms", headers=login("student"))
    assert r.status_code == 200
    assert [room["room_id"] for room in r.json()] == ["CSE-101", "CSE-102", "LAB-1"]
    assert "camera_stream" not in r.json()[0]


def test_list_rooms_filter_by_type(client, login):
    r = client.get("/api/rooms?type=lab", headers=login("student"))
    assert [room["room_id"] for room in r.json()] == ["LAB-1"]


def test_list_rooms_needs_login(client, world):
    assert client.get("/api/rooms").status_code == 401


# --- 9. Room status ---------------------------------------------------------

def test_status_shows_booking_and_free_rooms(client, login, db, world):
    add_booking(db, world, "CSE-101", at(FUTURE, 15), at(FUTURE, 16), purpose="DBMS")
    rooms = status_of(client, login("student"), FUTURE, "15:00", "16:00")

    booked = rooms["CSE-101"]
    assert booked["booking_status"] == "reserved"
    assert booked["booking"]["purpose"] == "DBMS"
    assert booked["booking"]["booked_by"]["name"] == "Prof. A"
    assert (booked["booking"]["start"], booked["booking"]["end"]) == ("15:00", "16:00")

    assert rooms["CSE-102"]["booking_status"] == "not_booked"
    assert rooms["CSE-102"]["booking"] is None


def test_status_partial_overlap_counts(client, login, db, world):
    add_booking(db, world, "CSE-101", at(FUTURE, 14, 30), at(FUTURE, 15, 30),
                status=BookingStatus.scheduled)
    rooms = status_of(client, login("student"), FUTURE, "15:00", "16:00")
    assert rooms["CSE-101"]["booking_status"] == "scheduled"


def test_status_ignores_cancelled_and_back_to_back(client, login, db, world):
    add_booking(db, world, "CSE-101", at(FUTURE, 15), at(FUTURE, 16), status=BookingStatus.cancelled)
    add_booking(db, world, "CSE-102", at(FUTURE, 14), at(FUTURE, 15))  # ends as slot starts
    rooms = status_of(client, login("student"), FUTURE, "15:00", "16:00")
    assert rooms["CSE-101"]["booking_status"] == "not_booked"
    assert rooms["CSE-102"]["booking_status"] == "not_booked"


def test_status_for_future_slot_has_no_occupancy(client, login, db):
    db.add(OccupancyReading(room_id="CSE-101", time=dt.datetime.now(IST), people_detected=True,
                            head_count=20, camera_status=CameraStatus.online))
    db.commit()
    rooms = status_of(client, login("student"), FUTURE, "15:00", "16:00")
    assert rooms["CSE-101"]["occupancy"] is None
    assert rooms["CSE-101"]["head_count"] is None


@pytest.fixture()
def current_slot():
    """A slot around the current minute, as date + "HH:MM" strings."""
    now = dt.datetime.now(IST)
    start, end = now - dt.timedelta(minutes=5), now + dt.timedelta(minutes=5)
    if start.date() != end.date():
        pytest.skip("Too close to midnight for a same-day slot.")
    return start.date(), start.strftime("%H:%M"), end.strftime("%H:%M")


def test_status_now_shows_live_occupancy(client, login, db, current_slot):
    now = dt.datetime.now(IST)
    db.add_all([
        # CSE-101: old reading then a newer one; only the newest counts.
        OccupancyReading(room_id="CSE-101", time=now - dt.timedelta(seconds=20),
                         people_detected=False, head_count=0, camera_status=CameraStatus.online),
        OccupancyReading(room_id="CSE-101", time=now - dt.timedelta(seconds=5),
                         people_detected=True, head_count=23, camera_status=CameraStatus.online),
        # CSE-102: camera reports offline.
        OccupancyReading(room_id="CSE-102", time=now - dt.timedelta(seconds=5),
                         people_detected=None, head_count=None, camera_status=CameraStatus.offline),
        # LAB-1: last reading is 5 minutes old, so too stale to trust.
        OccupancyReading(room_id="LAB-1", time=now - dt.timedelta(minutes=5),
                         people_detected=True, head_count=10, camera_status=CameraStatus.online),
    ])
    db.commit()

    day, start, end = current_slot
    rooms = status_of(client, login("student"), day, start, end)
    assert rooms["CSE-101"]["occupancy"] == "people_detected"
    assert rooms["CSE-101"]["head_count"] == 23
    assert rooms["CSE-101"]["last_reading_at"].endswith("+05:30")
    assert rooms["CSE-102"]["occupancy"] == "no_data"
    assert rooms["LAB-1"]["occupancy"] == "no_data"
    assert rooms["LAB-1"]["head_count"] is None


def test_status_now_with_no_readings_is_no_data(client, login, current_slot):
    day, start, end = current_slot
    rooms = status_of(client, login("student"), day, start, end)
    assert rooms["CSE-101"]["occupancy"] == "no_data"
    assert rooms["CSE-101"]["last_reading_at"] is None


def test_status_bad_slot(client, login):
    r = client.get("/api/rooms/status",
                   params={"date": FUTURE.isoformat(), "start": "16:00", "end": "15:00"},
                   headers=login("student"))
    assert r.status_code == 400
    r = client.get("/api/rooms/status", params={"date": FUTURE.isoformat()},
                   headers=login("student"))
    assert r.status_code == 400


# --- 10. Room schedule ------------------------------------------------------

def test_schedule_lists_active_bookings_in_order(client, login, db, world):
    add_booking(db, world, "CSE-101", at(FUTURE, 15), at(FUTURE, 16), purpose="Later")
    add_booking(db, world, "CSE-101", at(FUTURE, 9), at(FUTURE, 10), purpose="Earlier")
    add_booking(db, world, "CSE-101", at(FUTURE, 11), at(FUTURE, 12), purpose="Gone",
                status=BookingStatus.cancelled)
    add_booking(db, world, "CSE-101", at(FUTURE + dt.timedelta(days=1), 9),
                at(FUTURE + dt.timedelta(days=1), 10), purpose="Next day")
    add_booking(db, world, "CSE-102", at(FUTURE, 9), at(FUTURE, 10), purpose="Other room")

    r = client.get(f"/api/rooms/CSE-101/schedule?date={FUTURE.isoformat()}",
                   headers=login("student"))
    assert r.status_code == 200
    assert [b["purpose"] for b in r.json()] == ["Earlier", "Later"]


def test_schedule_unknown_room(client, login):
    r = client.get(f"/api/rooms/NOPE/schedule?date={FUTURE.isoformat()}", headers=login("student"))
    assert r.status_code == 404


# --- 11. Add a room ---------------------------------------------------------

NEW_ROOM = {"room_id": "cse-103", "name": "Classroom 103", "type": "classroom",
            "building": "Main", "floor": 1, "capacity": 60, "department": "cse",
            "camera_stream": "rtsp://user:secret@10.0.0.5/stream"}


def test_admin_adds_room_and_camera_address_stays_hidden(client, login):
    r = client.post("/api/rooms", json=NEW_ROOM, headers=login("admin"))
    assert r.status_code == 201, r.text
    room = r.json()
    assert room["room_id"] == "CSE-103"
    assert room["department"] == "CSE"
    assert room["has_camera"] is True
    assert "camera_stream" not in room
    listed = client.get("/api/rooms", headers=login("student")).json()
    assert "CSE-103" in [x["room_id"] for x in listed]
    assert all("camera_stream" not in x for x in listed)


def test_teacher_cannot_add_room(client, login):
    r = client.post("/api/rooms", json=NEW_ROOM, headers=login("teacher"))
    assert r.status_code == 403


def test_duplicate_room_is_rejected(client, login):
    r = client.post("/api/rooms", json={**NEW_ROOM, "room_id": "CSE-101"}, headers=login("admin"))
    assert r.status_code == 400


def test_bad_room_values_are_rejected(client, login):
    for bad in ({"room_id": "has space"}, {"type": "hall"}, {"capacity": 0}):
        r = client.post("/api/rooms", json={**NEW_ROOM, **bad}, headers=login("admin"))
        assert r.status_code == 400, bad
