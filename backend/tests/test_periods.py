"""The timetable grid's periods (app/periods.py and contract endpoint 26)."""

import datetime as dt

import pytest

from app.periods import PERIODS, get_period, period_at


# --- Plain helpers ----------------------------------------------------------

def test_periods_follow_each_other_without_gaps():
    for before, after in zip(PERIODS, PERIODS[1:]):
        assert before.end == after.start


def test_only_lunch_is_not_bookable():
    assert [p.code for p in PERIODS if not p.bookable] == ["lunch"]


def test_get_period():
    assert get_period("P5").start == dt.time(13, 45)
    assert get_period("P9") is None


@pytest.mark.parametrize("moment, code", [
    (dt.time(9, 0), "P1"),
    (dt.time(9, 59), "P1"),
    (dt.time(10, 0), "P2"),      # a period's end belongs to the next one
    (dt.time(13, 10), "lunch"),
    (dt.time(13, 45), "P5"),
    (dt.time(16, 44), "P7"),
])
def test_period_at(moment, code):
    assert period_at(moment).code == code


@pytest.mark.parametrize("moment", [dt.time(8, 59), dt.time(16, 45), dt.time(22, 0)])
def test_period_at_outside_the_college_day(moment):
    assert period_at(moment) is None


# --- Endpoint 26 ------------------------------------------------------------

def test_periods_endpoint(client, login):
    r = client.get("/api/periods", headers=login("student"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["days"] == ["monday", "tuesday", "wednesday", "thursday", "friday",
                            "saturday"]
    assert [p["period"] for p in body["periods"]] == [
        "P1", "P2", "P3", "P4", "lunch", "P5", "P6", "P7"]
    assert body["periods"][0] == {"period": "P1", "label": "P1", "start": "09:00",
                                  "end": "10:00", "bookable": True}
    assert body["periods"][4] == {"period": "lunch", "label": "Lunch break",
                                  "start": "13:00", "end": "13:45", "bookable": False}


def test_periods_need_a_login(client):
    assert client.get("/api/periods").status_code == 401
