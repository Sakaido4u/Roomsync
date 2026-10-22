"""Permission sweep: every protected endpoint, tried directly against the API
by every role that must NOT be allowed, plus logged-out and forged logins.

Each feature's own tests check what allowed roles can do. This file checks
the other side in one place: someone in class trying to get admin rights by
calling the API directly must always be refused, and nothing may change.
"""

import datetime as dt

import jwt
import pytest
from sqlalchemy import func, select

from app.config import IST, settings
from app.models import Booking, BookingStatus, Role, Room, SchoolClass, TimetableEntry, User
from app.security import JWT_ALGORITHM

ROLES = ["student", "teacher", "teacher2", "admin", "super_admin"]
FUTURE = (dt.datetime.now(IST) + dt.timedelta(days=30)).date().isoformat()


@pytest.fixture()
def setup(db, world):
    """Prof. A teaches CSE-7A and has a future booking; the student is not a CR."""
    db.get(SchoolClass, "CSE-7A").class_teacher_id = world["teacher"].id
    start = dt.datetime.fromisoformat(f"{FUTURE}T15:00:00+05:30")
    booking = Booking(room_id="CSE-101", user_id=world["teacher"].id, class_id="CSE-7A",
                      start_at=start, end_at=start + dt.timedelta(hours=1),
                      purpose="Extra class", status=BookingStatus.reserved,
                      reminder_sent_at=dt.datetime.now(IST))
    db.add(booking)
    db.commit()
    return booking.id


def endpoints(world, booking_id):
    """(method, path, body, roles allowed). Every other role must get 403."""
    teacher_id, admin_id = world["teacher"].id, world["admin"].id
    slot = {"date": FUTURE, "start": "17:00", "end": "18:00"}
    entry = {"room_id": "CSE-102", "class_id": "CSE-7A", "teacher_id": teacher_id,
             "subject": "Networks", "weekday": "monday", "start": "09:00", "end": "10:00"}
    return [
        ("POST", "/api/admin/admins", {"user_id": teacher_id}, {"super_admin"}),
        ("DELETE", f"/api/admin/admins/{admin_id}", None, {"super_admin"}),
        ("PUT", "/api/classes/CSE-7A/cr", {"student_id": world["student"].id}, {"teacher"}),
        ("POST", "/api/rooms", {"room_id": "HACK-1", "name": "Hack", "type": "classroom",
                                "building": "Main", "capacity": 10, "department": "CSE"},
         {"admin"}),
        ("POST", "/api/bookings", {"room_id": "CSE-102", **slot, "purpose": "Mine now"},
         {"teacher", "teacher2", "admin"}),
        ("GET", "/api/bookings/mine", None, {"teacher", "teacher2", "admin"}),
        ("DELETE", f"/api/bookings/{booking_id}", None, {"teacher"}),
        ("POST", f"/api/bookings/{booking_id}/override",
         {"purpose": "Taken", "reason": "Because"}, {"admin"}),
        ("POST", f"/api/bookings/{booking_id}/reschedule",
         {"room_id": "CSE-102", **slot, "reason": "Because"}, {"admin"}),
        ("POST", f"/api/bookings/{booking_id}/remove", {"reason": "Because"}, {"admin"}),
        ("POST", f"/api/bookings/{booking_id}/no-show-response", {"action": "release"},
         {"teacher"}),
        ("POST", "/api/timetable", {"semester_start": FUTURE, "semester_end": FUTURE,
                                    "entries": [entry]}, {"admin"}),
    ]


def snapshot(db, world, booking_id):
    """Everything a refused request might have changed."""
    db.expire_all()
    return {
        "roles": {u.college_id: u.role for u in db.scalars(select(User))},
        "crs": sorted(u.id for u in db.scalars(select(User).where(User.is_cr.is_(True)))),
        "booking": db.get(Booking, booking_id).status,
        "bookings": db.scalar(select(func.count()).select_from(Booking)),
        "rooms": db.scalar(select(func.count()).select_from(Room)),
        "timetable": db.scalar(select(func.count()).select_from(TimetableEntry)),
    }


def call(client, method, path, body, headers):
    return client.request(method, path, json=body, headers=headers)


def test_every_protected_endpoint_refuses_other_roles(client, login, world, db, setup):
    before = snapshot(db, world, setup)
    headers = {role: login(role) for role in ROLES}
    refused = 0
    for method, path, body, allowed in endpoints(world, setup):
        for role in ROLES:
            if role in allowed:
                continue
            r = call(client, method, path, body, headers[role])
            assert r.status_code == 403, f"{role} {method} {path} -> {r.status_code} {r.text}"
            assert r.json()["error"] == "forbidden"
            refused += 1
    assert refused > 40
    assert snapshot(db, world, setup) == before


@pytest.mark.parametrize("auth", [
    {},
    {"Authorization": "Bearer not-a-token"},
    {"Authorization": "Basic dXNlcjpwYXNz"},
])
def test_every_endpoint_needs_a_login(client, world, db, setup, auth):
    before = snapshot(db, world, setup)
    paths = [(m, p, b) for m, p, b, _ in endpoints(world, setup)] + [
        ("GET", "/api/auth/me", None),
        ("GET", "/api/rooms", None),
        ("GET", f"/api/rooms/status?date={FUTURE}&start=15:00&end=16:00", None),
        ("GET", f"/api/rooms/CSE-101/schedule?date={FUTURE}", None),
        ("GET", "/api/occupancy/CSE-101", None),
        ("GET", "/api/notifications", None),
        ("POST", "/api/notifications/1/read", None),
    ]
    for method, path, body in paths:
        r = call(client, method, path, body, auth)
        assert r.status_code == 401, f"{method} {path} -> {r.status_code} {r.text}"
        assert r.json()["error"] == "not_logged_in"
    assert snapshot(db, world, setup) == before


def forged(user_id, role="admin", secret=None, algorithm=JWT_ALGORITHM):
    payload = {"sub": str(user_id), "role": role,
               "exp": dt.datetime.now(IST) + dt.timedelta(hours=1)}
    return {"Authorization": "Bearer " + jwt.encode(payload, secret or settings.jwt_secret,
                                                    algorithm=algorithm)}


def test_role_written_in_the_token_is_ignored(client, world, db, setup):
    # Even a correctly signed token that claims "admin" only gets the role
    # stored in the database.
    for role in ("admin", "super_admin"):
        headers = forged(world["student"].id, role=role)
        assert client.post(f"/api/bookings/{setup}/remove", json={"reason": "x"},
                           headers=headers).status_code == 403
        assert client.post("/api/admin/admins", json={"user_id": world["student"].id},
                           headers=headers).status_code == 403
    db.expire_all()
    assert db.get(User, world["student"].id).role == Role.student


@pytest.mark.parametrize("headers", [
    "wrong-secret",
    "unsigned",
    "expired",
], ids=lambda h: h)
def test_forged_or_expired_tokens_are_refused(client, world, setup, headers):
    admin_id = world["admin"].id
    if headers == "wrong-secret":
        h = forged(admin_id, secret="a-guessed-secret-that-is-long-enough-1234")
    elif headers == "unsigned":
        token = jwt.encode({"sub": str(admin_id), "role": "admin"}, None, algorithm="none")
        h = {"Authorization": f"Bearer {token}"}
    else:
        payload = {"sub": str(admin_id), "exp": dt.datetime.now(IST) - dt.timedelta(minutes=1)}
        h = {"Authorization": "Bearer " + jwt.encode(payload, settings.jwt_secret,
                                                     algorithm=JWT_ALGORITHM)}
    r = client.post(f"/api/bookings/{setup}/remove", json={"reason": "x"}, headers=h)
    assert r.status_code == 401


def test_users_cannot_send_camera_readings(client, login, world):
    reading = {"room_id": "CSE-101", "people_detected": True, "head_count": 5,
               "camera_status": "online", "time": dt.datetime.now(IST).isoformat()}
    for role in ROLES:
        r = client.post("/api/occupancy", json=reading, headers=login(role))
        assert r.status_code == 401, role
