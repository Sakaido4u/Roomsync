"""Converting between the API's date + "HH:MM" and the database's date-times.

The API (see the contract) talks in a date plus start/end times in India
time. The database stores full date-times so it can compare ranges.
"""

from datetime import date, datetime, time

from app.config import IST


def combine(day: date, at: time) -> datetime:
    """2026-11-03 + 15:00  ->  2026-11-03 15:00 India time."""
    return datetime.combine(day, at.replace(second=0, microsecond=0), tzinfo=IST)


def now_ist() -> datetime:
    return datetime.now(IST)


def to_ist(moment: datetime) -> datetime:
    return moment.astimezone(IST)


def hhmm(moment: datetime) -> str:
    """Date-time -> "15:00" in India time."""
    return to_ist(moment).strftime("%H:%M")
