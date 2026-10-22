"""Admin override, reschedule, remove and notifications (contract endpoints 15-17, 22, 23)."""

import datetime as dt

import pytest
from sqlalchemy import func, select

from app import notify
from app.config import IST
from app.models import Booking, BookingStatus, ChangeLog, Notification

FUTURE = (dt.datetime.now(IST) + dt.timedelta(days=30)).date().isoformat()


def reserve(client, headers, room="CSE-101", start="15:00", end="16:00", **extra):
    body = {"room_id": room, "date": FUTURE, "start": start, "end": end,
            "purpose": "Extra class - DBMS", **extra}
    r = client.post("/api/bookings", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["booking_id"]


@pytest.fixture()
def cr(db, world):
    """Make the test student the CR of CSE-7A."""
    world["student"].is_cr = True
    db.commit()
    return world["student"]


def count(db, model) -> int:
    return db.scalar(select(func.count()).select_from(model))


# --- 15. Override -----------------------------------------------------------

def test_admin_override(client, login, db, cr):
    old_id = reserve(client, login("teacher"), class_id="CSE-7A")
    r = client.post(f"/api/bookings/{old_id}/override", headers=login("admin"),
                    json={"purpose": "Placement briefing", "reason": "Company visit moved"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["old_booking"] == {"booking_id": old_id, "booking_status": "overridden"}
    assert body["new_booking"]["booking_status"] == "reserved"
    assert body["notified"] == ["Prof. A", "CR of CSE-7A"]

    new = db.get(Booking, body["new_booking"]["booking_id"])
    old = db.get(Booking, old_id)
    assert (new.room_id, new.start_at, new.end_at) == (old.room_id, old.start_at, old.end_at)
    assert new.purpose == "Placement briefing"
    assert new.user_id != old.user_id

    log = db.scalar(select(ChangeLog))
    assert (log.action.value, log.reason, log.new_booking_id) == ("override", "Company visit moved", new.id)


def test_override_notifies_teacher_with_reason(client, login):
    old_id = reserve(client, login("teacher"))
    client.post(f"/api/bookings/{old_id}/override", headers=login("admin"),
                json={"purpose": "Briefing", "reason": "Company visit moved"})
    r = client.get("/api/notifications", headers=login("teacher"))
    assert r.status_code == 200
    [n] = r.json()
    assert n["type"] == "booking_overridden"
    assert n["booking_id"] == old_id
    assert n["read"] is False
    assert "Dr. HOD" in n["message"] and "Reason: Company visit moved" in n["message"]
    assert "CSE-101" in n["message"] and "15:00-16:00" in n["message"]


def test_override_cr_gets_class_message(client, login, cr):
    old_id = reserve(client, login("teacher"), class_id="CSE-7A")
    client.post(f"/api/bookings/{old_id}/override", headers=login("admin"),
                json={"purpose": "Briefing", "reason": "Company visit"})
    [n] = client.get("/api/notifications", headers=login("student")).json()
    assert n["message"].startswith("Your class's booking")


def test_no_cr_means_only_teacher_notified(client, login):
    old_id = reserve(client, login("teacher"), class_id="CSE-7A")  # class has no CR
    r = client.post(f"/api/bookings/{old_id}/override", headers=login("admin"),
                    json={"purpose": "Briefing", "reason": "Company visit"})
    assert r.json()["notified"] == ["Prof. A"]


def test_admin_overriding_own_booking_notifies_nobody(client, login, db):
    old_id = reserve(client, login("admin"))
    r = client.post(f"/api/bookings/{old_id}/override", headers=login("admin"),
                    json={"purpose": "Briefing", "reason": "Plans changed"})
    assert r.json()["notified"] == []
    assert count(db, Notification) == 0


def test_override_can_take_a_timetable_class(client, login, db, world):
    start = dt.datetime.fromisoformat(f"{FUTURE}T10:00").replace(tzinfo=IST)
    scheduled = Booking(room_id="CSE-101", user_id=world["teacher"].id, start_at=start,
                        end_at=start + dt.timedelta(hours=1), purpose="Networks",
                        status=BookingStatus.scheduled)
    db.add(scheduled)
    db.commit()
    r = client.post(f"/api/bookings/{scheduled.id}/override", headers=login("admin"),
                    json={"purpose": "Exam", "reason": "Internal assessment"})
    assert r.status_code == 200


# --- Rules shared by 15-17 ---------------------------------------------------

@pytest.mark.parametrize("action,extra", [
    ("override", {"purpose": "Briefing"}),
    ("reschedule", {"room_id": "CSE-102", "date": FUTURE, "start": "15:00", "end": "16:00"}),
    ("remove", {}),
])
def test_reason_is_required(client, login, db, action, extra):
    booking_id = reserve(client, login("teacher"))
    for reason in (None, "", "   "):
        body = dict(extra) if reason is None else {**extra, "reason": reason}
        r = client.post(f"/api/bookings/{booking_id}/{action}", json=body, headers=login("admin"))
        assert r.status_code == 400, (action, reason)
        assert r.json()["error"] == "reason_required"
    # Nothing changed and nobody was notified.
    assert db.get(Booking, booking_id).status == BookingStatus.reserved
    assert count(db, Notification) == 0 and count(db, ChangeLog) == 0


@pytest.mark.parametrize("who", ["teacher", "teacher2", "student"])
@pytest.mark.parametrize("action,extra", [
    ("override", {"purpose": "Briefing"}),
    ("reschedule", {"room_id": "CSE-102", "date": FUTURE, "start": "15:00", "end": "16:00"}),
    ("remove", {}),
])
def test_only_admins_can_change_bookings(client, login, who, action, extra):
    booking_id = reserve(client, login("teacher"))
    r = client.post(f"/api/bookings/{booking_id}/{action}", headers=login(who),
                    json={**extra, "reason": "I want it"})
    assert r.status_code == 403
    assert r.json()["error"] == "forbidden"


def test_cannot_change_inactive_or_missing_booking(client, login):
    booking_id = reserve(client, login("teacher"))
    client.delete(f"/api/bookings/{booking_id}", headers=login("teacher"))  # cancelled
    r = client.post(f"/api/bookings/{booking_id}/remove", headers=login("admin"),
                    json={"reason": "x"})
    assert r.status_code == 400
    r = client.post("/api/bookings/9999/remove", headers=login("admin"), json={"reason": "x"})
    assert r.status_code == 404


def test_cannot_change_a_booking_that_has_ended(client, login, db, world):
    start = dt.datetime.now(IST) - dt.timedelta(hours=3)
    past = Booking(room_id="CSE-101", user_id=world["teacher"].id, start_at=start,
                   end_at=start + dt.timedelta(hours=1), purpose="Old",
                   status=BookingStatus.reserved)
    db.add(past)
    db.commit()
    r = client.post(f"/api/bookings/{past.id}/remove", headers=login("admin"),
                    json={"reason": "cleanup"})
    assert r.status_code == 400


# --- 16. Reschedule ---------------------------------------------------------

def test_reschedule_moves_booking_and_frees_old_slot(client, login, db, cr):
    booking_id = reserve(client, login("teacher"), class_id="CSE-7A")
    r = client.post(f"/api/bookings/{booking_id}/reschedule", headers=login("admin"), json={
        "room_id": "CSE-102", "date": FUTURE, "start": "15:00", "end": "16:00",
        "reason": "Projector under repair"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["booking_id"] == booking_id
    assert body["room_id"] == "CSE-102"
    assert body["booking_status"] == "reserved"
    assert body["notified"] == ["Prof. A", "CR of CSE-7A"]

    [n] = client.get("/api/notifications", headers=login("teacher")).json()
    assert n["type"] == "booking_rescheduled"
    assert "moved to CSE-102" in n["message"]

    # The old slot is free again.
    reserve(client, login("teacher2"), room="CSE-101")


def test_reschedule_within_same_room_overlapping_itself(client, login):
    booking_id = reserve(client, login("teacher"), start="15:00", end="16:00")
    r = client.post(f"/api/bookings/{booking_id}/reschedule", headers=login("admin"), json={
        "room_id": "CSE-101", "date": FUTURE, "start": "15:30", "end": "16:30",
        "reason": "Starts later"})
    assert r.status_code == 200, r.text
    assert (r.json()["start"], r.json()["end"]) == ("15:30", "16:30")


def test_reschedule_into_taken_slot_gives_conflict_and_changes_nothing(client, login, db):
    mine = reserve(client, login("teacher"), room="CSE-101")
    theirs = reserve(client, login("teacher2"), room="CSE-102", purpose="Lab prep")
    r = client.post(f"/api/bookings/{mine}/reschedule", headers=login("admin"), json={
        "room_id": "CSE-102", "date": FUTURE, "start": "15:00", "end": "16:00",
        "reason": "Move"})
    assert r.status_code == 409
    assert r.json()["existing_booking"]["booking_id"] == theirs
    db.expire_all()
    assert db.get(Booking, mine).room_id == "CSE-101"
    assert count(db, Notification) == 0 and count(db, ChangeLog) == 0


def test_reschedule_rejects_bad_times(client, login):
    booking_id = reserve(client, login("teacher"))
    admin = login("admin")
    base = {"room_id": "CSE-102", "date": FUTURE, "reason": "x"}
    for times in ({"start": "16:00", "end": "15:00"},
                  {"start": "15:00", "end": "16:00", "date": "2020-01-01"}):
        r = client.post(f"/api/bookings/{booking_id}/reschedule", headers=admin,
                        json={**base, **times})
        assert r.status_code == 400, times
    r = client.post(f"/api/bookings/{booking_id}/reschedule", headers=admin, json={
        "room_id": "CSE-101", "date": FUTURE, "start": "15:00", "end": "16:00", "reason": "x"})
    assert r.status_code == 400  # nothing would change


# --- 17. Remove -------------------------------------------------------------

def test_remove_frees_slot_and_notifies(client, login, db):
    booking_id = reserve(client, login("teacher"))
    r = client.post(f"/api/bookings/{booking_id}/remove", headers=login("admin"),
                    json={"reason": "Department event"})
    assert r.status_code == 200
    assert r.json()["booking_status"] == "cancelled"
    assert r.json()["notified"] == ["Prof. A"]
    [n] = client.get("/api/notifications", headers=login("teacher")).json()
    assert n["type"] == "booking_removed"
    assert "Reason: Department event" in n["message"]
    reserve(client, login("teacher2"))  # slot is free


# --- 22, 23. Notifications --------------------------------------------------

def test_notifications_newest_first_and_unread_filter(client, login):
    teacher, admin = login("teacher"), login("admin")
    first = reserve(client, teacher, start="09:00", end="10:00")
    second = reserve(client, teacher, start="11:00", end="12:00")
    client.post(f"/api/bookings/{first}/remove", headers=admin, json={"reason": "one"})
    client.post(f"/api/bookings/{second}/remove", headers=admin, json={"reason": "two"})

    notes = client.get("/api/notifications", headers=teacher).json()
    assert [n["booking_id"] for n in notes] == [second, first]

    r = client.post(f"/api/notifications/{notes[0]['notification_id']}/read", headers=teacher)
    assert r.status_code == 200
    assert r.json() == {"notification_id": notes[0]["notification_id"], "read": True}

    unread = client.get("/api/notifications?unread=true", headers=teacher).json()
    assert [n["booking_id"] for n in unread] == [first]


def test_cannot_read_or_mark_someone_elses_notifications(client, login):
    booking_id = reserve(client, login("teacher"))
    client.post(f"/api/bookings/{booking_id}/remove", headers=login("admin"), json={"reason": "x"})
    [n] = client.get("/api/notifications", headers=login("teacher")).json()
    assert client.get("/api/notifications", headers=login("teacher2")).json() == []
    r = client.post(f"/api/notifications/{n['notification_id']}/read", headers=login("teacher2"))
    assert r.status_code == 403
    assert client.post("/api/notifications/9999/read", headers=login("teacher")).status_code == 404


def test_notifications_need_login(client, world):
    assert client.get("/api/notifications").status_code == 401


# --- Email copies -------------------------------------------------------------

class FakeSMTP:
    sent: list = []

    def __init__(self, host, port, timeout):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        pass

    def login(self, user, password):
        pass

    def send_message(self, msg):
        FakeSMTP.sent.append(msg)


def test_email_copy_is_sent_when_smtp_is_set_up(client, login, monkeypatch, cr):
    monkeypatch.setattr(notify.settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(notify.settings, "smtp_user", "roomsync@example.com")
    monkeypatch.setattr(notify.settings, "smtp_password", "app-password")
    monkeypatch.setattr(notify.smtplib, "SMTP", FakeSMTP)
    FakeSMTP.sent = []

    booking_id = reserve(client, login("teacher"), class_id="CSE-7A")
    client.post(f"/api/bookings/{booking_id}/remove", headers=login("admin"),
                json={"reason": "Department event"})

    assert sorted(m["To"] for m in FakeSMTP.sent) == ["s1@example.com", "t1@example.com"]
    assert all("Reason: Department event" in m.get_content() for m in FakeSMTP.sent)


def test_no_email_without_smtp_settings(client, login, monkeypatch):
    monkeypatch.setattr(notify.settings, "smtp_host", "")

    def explode(*args, **kwargs):
        raise AssertionError("should not connect")

    monkeypatch.setattr(notify.smtplib, "SMTP", explode)
    booking_id = reserve(client, login("teacher"))
    r = client.post(f"/api/bookings/{booking_id}/remove", headers=login("admin"),
                    json={"reason": "x"})
    assert r.status_code == 200
