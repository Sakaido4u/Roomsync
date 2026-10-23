"""The timetable grid's week view (contract endpoint 33)."""

import datetime as dt

import pytest

from app.config import IST
from app.models import (
    Booking,
    BookingStatus,
    CameraStatus,
    OccupancyReading,
    Room,
    SchoolClass,
    Subject,
    SubjectType,
)
from app.routers.week import Placed, build_cells, monday_of, week_view
from app.schemas import TeacherRef, WeekEntry
from app.timeutil import combine

TODAY = dt.datetime.now(IST).date()
# A Monday at least a week away, so all its classes are still in the future.
MONDAY = TODAY + dt.timedelta(days=7 + (7 - TODAY.weekday()) % 7)
TUESDAY = MONDAY + dt.timedelta(days=1)
SATURDAY = MONDAY + dt.timedelta(days=5)
LAST_MONDAY = monday_of(TODAY) - dt.timedelta(days=7)


# --- build_cells, on its own -------------------------------------------------

def fake(start, end, batch=None):
    t = lambda s: dt.time.fromisoformat(s)
    entry = WeekEntry(
        booking_id=1, timetable_entry_id=None, subject_code=None, title="X", purpose="X",
        teacher=TeacherRef(user_id=1, college_id="T1", name="A", initials=None),
        class_id=None, batch=batch, room_id="R", start=start, end=end,
        booking_status="reserved", is_extra=True, change=None, occupancy=None)
    return Placed(MONDAY, t(start), t(end), entry)


def test_empty_day_is_eight_single_cells():
    cells, outside = build_cells([])
    assert [c.periods for c in cells] == [["P1"], ["P2"], ["P3"], ["P4"], ["lunch"], ["P5"],
                                          ["P6"], ["P7"]]
    assert all(c.entries == [] for c in cells) and outside == []
    assert [c.bookable for c in cells].count(False) == 1


def test_two_period_lab_is_one_cell_with_both_batches():
    cells, _ = build_cells([fake("14:45", "16:45", "A2"), fake("14:45", "16:45", "A1")])
    lab = cells[-1]
    assert (lab.period, lab.periods, lab.start, lab.end) == ("P6", ["P6", "P7"], "14:45", "16:45")
    assert [e.batch for e in lab.entries] == ["A1", "A2"]
    assert len(cells) == 7


def test_whole_morning_is_one_cell_and_lunch_stays_apart():
    cells, _ = build_cells([fake("09:00", "13:00"), fake("13:45", "16:45")])
    assert [c.periods for c in cells] == [["P1", "P2", "P3", "P4"], ["lunch"],
                                          ["P5", "P6", "P7"]]


def test_free_time_booking_lands_in_every_period_it_touches():
    cells, _ = build_cells([fake("15:00", "16:00")])
    assert cells[-1].periods == ["P6", "P7"]


def test_booking_outside_every_period():
    cells, outside = build_cells([fake("17:30", "18:30")])
    assert all(c.entries == [] for c in cells)
    assert [e.start for e in outside] == ["17:30"]


# --- A small college with a timetable ---------------------------------------

@pytest.fixture()
def college(client, login, db, world):
    """CSE-7A's timetable: Mon P1 BCS702 (T1, CSE-101); Mon P4 open elective
    (T2, no room); Tue P6-P7 lab, batch A1 with T1 in LAB-1 and batch A2
    with T2 in CSE-102."""
    db.add_all([
        Subject(code="BCS702", title="Parallel Computing", type=SubjectType.ipcc, credits=4,
                department="CSE"),
        Subject(code="OE-7", title="Open Elective", type=SubjectType.oec, credits=3,
                department="CSE"),
    ])
    cls = db.get(SchoolClass, "CSE-7A")
    cls.semester_label, cls.home_room_id, cls.strength = "VII-A", "CSE-101", 50
    world["teacher"].initials = "PA"
    db.commit()

    def slot(weekday, start, end, teacher, code, room=None, batch=None):
        e = {"class_id": "CSE-7A", "teacher": teacher, "subject_code": code,
             "weekday": weekday, "start": start, "end": end}
        if room:
            e["room_id"] = room
        if batch:
            e["batch"] = batch
        return e

    r = client.post("/api/timetable", headers=login("admin"), json={
        "semester_start": (LAST_MONDAY - dt.timedelta(days=14)).isoformat(),
        "semester_end": (MONDAY + dt.timedelta(days=27)).isoformat(),
        "entries": [
            slot("monday", "09:00", "10:00", "T1", "BCS702", "CSE-101"),
            slot("monday", "12:00", "13:00", "T2", "OE-7"),
            slot("tuesday", "14:45", "16:45", "T1", "BCS702", "LAB-1", "A1"),
            slot("tuesday", "14:45", "16:45", "T2", "BCS702", "CSE-102", "A2"),
        ],
    })
    assert r.status_code == 200, r.text
    assert r.json()["clashes"] == [] and r.json()["skipped_dates"] == []


def week(client, headers, start=MONDAY, **params):
    r = client.get("/api/timetable/week", params={"week_start": start.isoformat(), **params},
                   headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def cell(body, day, period):
    """The cell of `day` (a date) that covers `period`."""
    found = next(d for d in body["days"] if d["date"] == day.isoformat())
    return next(c for c in found["cells"] if period in c["periods"])


def test_teacher_week(client, login, college):
    body = week(client, login("teacher"), start=MONDAY + dt.timedelta(days=2), teacher="T1")
    assert (body["week_start"], body["week_end"]) == (MONDAY.isoformat(), SATURDAY.isoformat())
    assert [d["weekday"] for d in body["days"]] == [
        "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]
    assert body["view"]["kind"] == "teacher"
    assert body["view"]["teacher"]["initials"] == "PA"

    [p1] = cell(body, MONDAY, "P1")["entries"]
    assert p1["booking_id"] is not None
    assert (p1["subject_code"], p1["title"], p1["room_id"], p1["class_id"]) == (
        "BCS702", "Parallel Computing", "CSE-101", "CSE-7A")
    assert (p1["booking_status"], p1["is_extra"], p1["change"], p1["batch"]) == (
        "scheduled", False, None, None)
    assert p1["teacher"]["college_id"] == "T1"

    assert cell(body, MONDAY, "P2")["entries"] == []          # a free period
    assert cell(body, MONDAY, "P4")["entries"] == []          # the elective is T2's
    assert cell(body, MONDAY, "lunch")["bookable"] is False

    lab = cell(body, TUESDAY, "P7")
    assert lab["periods"] == ["P6", "P7"]
    assert [(e["batch"], e["room_id"]) for e in lab["entries"]] == [("A1", "LAB-1")]


def test_class_week_has_both_batches_and_the_roomless_elective(client, login, college):
    body = week(client, login("student"), class_id="CSE-7A")
    assert body["view"]["class_info"]["semester_label"] == "VII-A"

    [elective] = cell(body, MONDAY, "P4")["entries"]
    assert (elective["booking_id"], elective["room_id"], elective["title"]) == (
        None, None, "Open Elective")
    assert elective["booking_status"] == "scheduled"

    lab = cell(body, TUESDAY, "P6")
    assert [(e["batch"], e["room_id"], e["teacher"]["college_id"]) for e in lab["entries"]] == [
        ("A1", "LAB-1", "T1"), ("A2", "CSE-102", "T2")]


def test_room_week(client, login, college):
    body = week(client, login("teacher"), room_id="LAB-1")
    assert body["view"]["room"]["room_id"] == "LAB-1"
    assert body["room_occupancy"] is None                    # not this week
    filled = [(d["weekday"], c["period"]) for d in body["days"] for c in d["cells"]
              if c["entries"]]
    assert filled == [("tuesday", "P6")]


def test_extra_class_is_marked(client, login, college):
    r = client.post("/api/bookings", headers=login("teacher"), json={
        "room_id": "CSE-101", "date": SATURDAY.isoformat(), "period": "P2",
        "class_id": "CSE-7A", "subject_code": "BCS702"})
    assert r.status_code == 201, r.text
    for params in ({"teacher": "T1"}, {"class_id": "CSE-7A"}, {"room_id": "CSE-101"}):
        [extra] = cell(week(client, login("student"), **params), SATURDAY, "P2")["entries"]
        assert (extra["is_extra"], extra["subject_code"], extra["title"]) == (
            True, "BCS702", "Parallel Computing")
        assert extra["booking_status"] == "reserved"


def test_moved_class_shows_where_and_why(client, login, college):
    [p1] = cell(week(client, login("teacher"), teacher="T1"), MONDAY, "P1")["entries"]
    r = client.post(f"/api/bookings/{p1['booking_id']}/reschedule", headers=login("admin"), json={
        "room_id": "CSE-102", "date": MONDAY.isoformat(), "start": "09:00", "end": "10:00",
        "reason": "CSE-101 projector under repair"})
    assert r.status_code == 200, r.text

    [moved] = cell(week(client, login("teacher"), teacher="T1"), MONDAY, "P1")["entries"]
    assert (moved["room_id"], moved["booking_status"]) == ("CSE-102", "scheduled")
    assert moved["change"]["action"] == "reschedule"
    assert moved["change"]["reason"] == "CSE-101 projector under repair"
    assert moved["change"]["by"] == "Dr. HOD"
    assert "CSE-101" in moved["change"]["details"] and "CSE-102" in moved["change"]["details"]
    # The room it left is free that period; the room it moved to has it.
    assert cell(week(client, login("teacher"), room_id="CSE-101"), MONDAY, "P1")["entries"] == []
    assert len(cell(week(client, login("teacher"), room_id="CSE-102"), MONDAY, "P1")["entries"]) == 1


def test_removed_and_overridden_classes_stay_visible(client, login, college):
    body = week(client, login("teacher"), teacher="T1")
    [p1] = cell(body, MONDAY, "P1")["entries"]
    [lab] = cell(body, TUESDAY, "P6")["entries"]
    admin = login("admin")
    client.post(f"/api/bookings/{p1['booking_id']}/remove", headers=admin,
                json={"reason": "Holiday"})
    client.post(f"/api/bookings/{lab['booking_id']}/override", headers=admin,
                json={"purpose": "Placement test", "reason": "Company visit"})

    body = week(client, login("teacher"), teacher="T1")
    [removed] = cell(body, MONDAY, "P1")["entries"]
    assert (removed["booking_status"], removed["change"]["action"]) == ("cancelled", "remove")
    [overridden] = cell(body, TUESDAY, "P6")["entries"]
    assert (overridden["booking_status"], overridden["change"]["reason"]) == (
        "overridden", "Company visit")
    # The room's own week shows the admin's booking that took the slot.
    statuses = [e["booking_status"] for e in
                cell(week(client, login("teacher"), room_id="LAB-1"), TUESDAY, "P6")["entries"]]
    assert sorted(statuses) == ["overridden", "reserved"]


def test_reservation_cancelled_by_its_teacher_disappears(client, login, college):
    r = client.post("/api/bookings", headers=login("teacher"), json={
        "room_id": "CSE-102", "date": MONDAY.isoformat(), "period": "P3", "purpose": "Meeting"})
    client.delete(f"/api/bookings/{r.json()['booking_id']}", headers=login("teacher"))
    assert cell(week(client, login("teacher"), teacher="T1"), MONDAY, "P3")["entries"] == []


def test_past_week_shows_the_timetable(client, login, college):
    # Last week is over and the upload only booked future classes, so these
    # come from the timetable itself.
    body = week(client, login("student"), start=LAST_MONDAY, class_id="CSE-7A")
    [p1] = cell(body, LAST_MONDAY, "P1")["entries"]
    assert (p1["booking_id"], p1["room_id"], p1["title"]) == (None, "CSE-101",
                                                              "Parallel Computing")


def test_running_class_carries_live_detection(db, world):
    """Uses week_view directly, with a chosen 'now' (Monday 11:30)."""
    now = combine(MONDAY, dt.time(11, 30))
    db.add(Booking(room_id="CSE-101", user_id=world["teacher"].id,
                   start_at=combine(MONDAY, dt.time(11)), end_at=combine(MONDAY, dt.time(12)),
                   purpose="Seminar", status=BookingStatus.reserved))
    db.add(OccupancyReading(room_id="CSE-101", time=now - dt.timedelta(seconds=5),
                            people_detected=True, head_count=3,
                            camera_status=CameraStatus.online))
    db.commit()

    body = week_view(db, MONDAY, now, room=db.get(Room, "CSE-101"))
    assert (body.today, body.current_period) == (MONDAY, "P3")
    [running] = next(c for c in body.days[0].cells if c.period == "P3").entries
    assert (running.occupancy.occupancy, running.occupancy.head_count) == ("people_detected", 3)
    assert body.room_occupancy.occupancy == "people_detected"

    later = week_view(db, MONDAY, now + dt.timedelta(hours=1), room=db.get(Room, "CSE-101"))
    [finished] = next(c for c in later.days[0].cells if c.period == "P3").entries
    assert finished.occupancy is None
    assert later.current_period == "P4"


# --- Errors --------------------------------------------------------------------

@pytest.mark.parametrize("params, status, words", [
    ({}, 400, "exactly one of"),
    ({"teacher": "T1", "class_id": "CSE-7A"}, 400, "exactly one of"),
    ({"teacher": "NOBODY"}, 404, "NOBODY does not exist"),
    ({"teacher": "S1"}, 400, "is not an active teacher"),
    ({"class_id": "CSE-9Z"}, 404, "Class CSE-9Z does not exist"),
    ({"room_id": "NOPE"}, 404, "Room NOPE does not exist"),
    ({"room_id": "CSE-101", "week_start": "not-a-date"}, 400, "week_start"),
])
def test_week_bad_input(client, login, world, params, status, words):
    r = client.get("/api/timetable/week", params=params, headers=login("student"))
    assert r.status_code == status, r.text
    assert words in r.json()["message"]


def test_week_needs_a_login(client, world):
    assert client.get("/api/timetable/week", params={"room_id": "CSE-101"}).status_code == 401


def test_timetable_class_without_a_booking_shows_once_it_has_started(db, world):
    """The upload never books a class that has already started, so a class
    running at upload time comes from the timetable itself."""
    from app.models import TimetableEntry
    db.add(TimetableEntry(room_id="CSE-101", class_id="CSE-7A", teacher_id=world["teacher"].id,
                          subject="Networks", weekday=0, start_time=dt.time(9),
                          end_time=dt.time(10), semester_start=MONDAY,
                          semester_end=MONDAY + dt.timedelta(days=6)))
    db.commit()
    cls = db.get(SchoolClass, "CSE-7A")

    def p1(now):
        body = week_view(db, MONDAY, now, school_class=cls)
        return body.days[0].cells[0].entries

    assert p1(combine(MONDAY, dt.time(8, 0))) == []          # not started: skipped/removed
    [running] = p1(combine(MONDAY, dt.time(9, 30)))
    assert (running.booking_id, running.room_id) == (None, "CSE-101")
