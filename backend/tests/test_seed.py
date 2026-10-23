"""The demo data (app/seed.py) matches handoff 2's tables and demo needs."""

import datetime as dt

import pytest
from sqlalchemy import func, select

from app.models import (
    Booking,
    ChangeLog,
    Notification,
    NotificationType,
    Room,
    SchoolClass,
    Subject,
    TeachingAssignment,
)
from app.routers.week import monday_of, week_view
from app.seed import SEMESTER_END, seed
from app.timeutil import now_ist


@pytest.fixture()
def demo(db):
    people = seed(db)
    db.expire_all()
    return people


def entries(body):
    return [e for d in body.days for c in d.cells for e in c.entries]


def cell(body, weekday, period):
    day = body.days[weekday]
    return next(c for c in day.cells if period in c.periods)


def test_people_rooms_classes_subjects(db, demo):
    assert set(demo) == {"SA001", "T001", "T002", "T003", "T004", "T005",
                         "1JS23CS044", "1JS23CS039"}
    assert (demo["T001"].role.value, demo["T001"].initials) == ("admin", "KRA")
    assert demo["1JS23CS044"].is_cr and demo["1JS23CS044"].class_id == "CSE-7A"

    rooms = {r.room_id: r for r in db.scalars(select(Room))}
    assert set(rooms) == {"A-312", "A-313", "A-310", "A-219", "A-202", "B-303", "B-304",
                          "B-305", "B-309", "CSE-101", "MR-1"}
    assert rooms["CSE-101"].has_camera and rooms["MR-1"].capacity == 12
    assert rooms["A-310"].capacity == 36

    cse7a = db.get(SchoolClass, "CSE-7A")
    assert (cse7a.semester_label, cse7a.home_room_id, cse7a.strength, cse7a.wef_date) == (
        "VII-A", "A-312", 64, dt.date(2026, 7, 20))
    assert cse7a.class_teacher_id == demo["T002"].id
    assert db.scalar(select(func.count()).select_from(Subject)) == 6


def test_who_teaches_what_comes_from_the_timetable(db, demo):
    rows = db.scalars(select(TeachingAssignment).where(
        TeachingAssignment.teacher_id == demo["T002"].id)).all()
    assert sorted((r.class_id, r.batch or "") for r in rows) == [
        ("CSE-7A", ""), ("CSE-7A", "A1"), ("CSE-7A", "A2"), ("CSE-7B", "")]
    assert {r.subject_code for r in rows} == {"BCS702"}


@pytest.mark.skipif(now_ist().date() > SEMESTER_END, reason="semester is over")
def test_sharmas_week(db, demo):
    body = week_view(db, monday_of(now_ist().date()), now_ist(), teacher=demo["T002"])
    regular = [e for e in entries(body) if not e.is_extra]
    extra = [e for e in entries(body) if e.is_extra]
    # 8 regular slots (each lab is one), plus the Saturday extra class.
    assert len(regular) == 8
    assert [(e.subject_code, e.room_id, e.start) for e in extra] == [
        ("BCS702", "A-312", "10:00")]
    assert cell(body, 5, "P2").entries == extra
    lab = cell(body, 1, "P6")
    assert (lab.periods, [e.room_id for e in lab.entries]) == (["P6", "P7"], ["A-202"])


@pytest.mark.skipif(now_ist().date() > SEMESTER_END, reason="semester is over")
def test_next_cse_7b_class_is_moved_with_a_notification(db, demo):
    [log] = db.scalars(select(ChangeLog)).all()
    assert (log.action.value, log.reason) == ("reschedule", "A-313 projector under repair")
    assert log.done_by == demo["T001"].id
    moved = db.get(Booking, log.booking_id)
    assert (moved.class_id, moved.room_id) == ("CSE-7B", "B-303")
    [note] = db.scalars(select(Notification)).all()
    assert (note.user_id, note.type) == (demo["T002"].id, NotificationType.booking_rescheduled)


def test_class_sheet(db, demo):
    body = week_view(db, monday_of(now_ist().date()), now_ist(),
                     school_class=db.get(SchoolClass, "CSE-7A"))
    thursday_morning = cell(body, 3, "P1")
    assert thursday_morning.periods == ["P1", "P2", "P3", "P4"]
    [project] = thursday_morning.entries
    assert (project.title, project.room_id) == ("Major Project Phase-II", None)
    assert [e.batch for e in cell(body, 1, "P6").entries] == ["A1", "A2"]
    [elective] = cell(body, 0, "P4").entries
    assert (elective.subject_code, elective.room_id) == ("OE-7", None)


def test_demo_periods_are_free_in_a312(db, demo):
    body = week_view(db, monday_of(now_ist().date()), now_ist(), room=db.get(Room, "A-312"))
    assert cell(body, 0, "P7").entries == []
    assert cell(body, 5, "P1").entries == []
