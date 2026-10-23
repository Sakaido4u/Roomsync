"""The college's fixed teaching periods and days.

This is the ONE place the timetable grid's columns and rows are defined.
The dashboard reads them from GET /api/periods, so changing a time here
changes it everywhere, and nothing else in the code types "09:00".

The lunch break is listed too (the grid shows it as a narrow column) but
is not bookable.
"""

from dataclasses import dataclass
from datetime import time


@dataclass(frozen=True)
class Period:
    code: str       # "P1" ... "P7", or "lunch"
    label: str      # what the grid's column header shows
    start: time
    end: time
    bookable: bool = True


PERIODS: tuple[Period, ...] = (
    Period("P1", "P1", time(9, 0), time(10, 0)),
    Period("P2", "P2", time(10, 0), time(11, 0)),
    Period("P3", "P3", time(11, 0), time(12, 0)),
    Period("P4", "P4", time(12, 0), time(13, 0)),
    Period("lunch", "Lunch break", time(13, 0), time(13, 45), bookable=False),
    Period("P5", "P5", time(13, 45), time(14, 45)),
    Period("P6", "P6", time(14, 45), time(15, 45)),
    Period("P7", "P7", time(15, 45), time(16, 45)),
)

# Rows of the grid, Monday to Saturday. Same numbering as Python's
# date.weekday() (0 = Monday), which is also what the database stores.
TEACHING_DAYS: tuple[int, ...] = (0, 1, 2, 3, 4, 5)

WEEKDAY_NAMES = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def get_period(code: str) -> Period | None:
    """The period with this code ("P3"), or None."""
    return next((p for p in PERIODS if p.code == code), None)


def period_at(moment: time) -> Period | None:
    """The period running at this time of day (lunch included), or None
    before 09:00, after 16:45 and so on. A period includes its start
    minute but not its end, so 10:00 is P2, not P1."""
    return next((p for p in PERIODS if p.start <= moment < p.end), None)
