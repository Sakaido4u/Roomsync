"""Camera readings (contract endpoints 20 and 21)."""

import datetime as dt

from sqlalchemy import func, select

from app.config import IST, settings
from app.models import OccupancyReading

KEY = {"X-Device-Key": settings.device_key}


def now() -> dt.datetime:
    return dt.datetime.now(IST)


def reading(**changes) -> dict:
    body = {"room_id": "CSE-101", "people_detected": True, "head_count": 23,
            "camera_status": "online", "time": now().isoformat()}
    body.update(changes)
    return body


def send(client, headers=KEY, **changes):
    return client.post("/api/occupancy", json=reading(**changes), headers=headers)


def latest(client, headers, room="CSE-101"):
    r = client.get(f"/api/occupancy/{room}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


# --- 20. Sending readings ---------------------------------------------------

def test_camera_reading_is_stored_and_shown(client, login):
    r = send(client)
    assert r.status_code == 201, r.text
    assert r.json() == {"received": True}

    out = latest(client, login("student"))
    assert out["occupancy"] == "people_detected"
    assert out["head_count"] == 23
    assert out["last_reading_at"].endswith("+05:30")


def test_empty_room(client, login):
    assert send(client, people_detected=False, head_count=0).status_code == 201
    assert latest(client, login("student"))["occupancy"] == "not_detected"


def test_newest_reading_wins(client, login):
    send(client, people_detected=False, head_count=0,
         time=(now() - dt.timedelta(seconds=10)).isoformat())
    send(client, people_detected=True, head_count=5)
    assert latest(client, login("student"))["head_count"] == 5


def test_offline_camera_shows_no_data(client, login):
    # Even if the camera program sends numbers, offline means "unknown".
    assert send(client, camera_status="offline", people_detected=True, head_count=9).status_code == 201
    out = latest(client, login("student"))
    assert out["occupancy"] == "no_data"
    assert out["head_count"] is None


def test_no_readings_yet_shows_no_data(client, login):
    out = latest(client, login("student"))
    assert out == {"room_id": "CSE-101", "occupancy": "no_data", "head_count": None,
                   "last_reading_at": None}


def test_old_reading_shows_no_data(client, login):
    send(client, time=(now() - dt.timedelta(minutes=5)).isoformat())
    assert latest(client, login("student"))["occupancy"] == "no_data"


def test_time_without_zone_is_india_time(client, login):
    naive = now().replace(tzinfo=None).isoformat()
    assert send(client, time=naive).status_code == 201
    assert latest(client, login("student"))["occupancy"] == "people_detected"


def test_wrong_or_missing_device_key_is_refused(client, world):
    assert send(client, headers={"X-Device-Key": "guess"}).status_code == 401
    r = send(client, headers={})
    assert r.status_code == 401
    assert r.json()["error"] == "not_logged_in"


def test_user_login_is_not_enough_to_send_readings(client, login):
    # Even an admin cannot pretend to be a camera.
    assert send(client, headers=login("admin")).status_code == 401


def test_unknown_room(client, world):
    assert send(client, room_id="NOPE").status_code == 404


def test_inconsistent_readings_are_refused(client, world):
    assert send(client, people_detected=None).status_code == 400
    assert send(client, people_detected=False, head_count=4).status_code == 400
    assert send(client, people_detected=True, head_count=0).status_code == 400
    assert send(client, head_count=-1).status_code == 400
    assert send(client, camera_status="broken").status_code == 400


def test_future_time_is_refused(client, world):
    assert send(client, time=(now() + dt.timedelta(minutes=10)).isoformat()).status_code == 400


def test_old_readings_are_cleaned_up(client, world, db):
    db.add(OccupancyReading(room_id="CSE-101", time=now() - dt.timedelta(days=30),
                            people_detected=False, head_count=0, camera_status="online"))
    db.commit()
    send(client)
    count = db.scalar(select(func.count()).select_from(OccupancyReading))
    assert count == 1  # only the new one remains


# --- 21. Reading the latest value ------------------------------------------

def test_latest_needs_login(client, world):
    assert client.get("/api/occupancy/CSE-101").status_code == 401


def test_latest_unknown_room(client, login):
    assert client.get("/api/occupancy/NOPE", headers=login("student")).status_code == 404


def test_reading_shows_on_room_status_grid(client, login):
    """End to end: camera sends -> dashboard grid shows it."""
    send(client, head_count=17)
    start, end = now() - dt.timedelta(minutes=5), now() + dt.timedelta(minutes=5)
    if start.date() != end.date():
        return  # too close to midnight for a same-day slot
    r = client.get("/api/rooms/status", headers=login("student"), params={
        "date": start.date().isoformat(), "start": start.strftime("%H:%M"),
        "end": end.strftime("%H:%M")})
    room = {x["room_id"]: x for x in r.json()}["CSE-101"]
    assert (room["occupancy"], room["head_count"]) == ("people_detected", 17)
