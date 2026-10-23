"""The timetable grid's periods and days (API contract endpoint 26).

The dashboard draws its columns and rows from this reply, so the times
live only in app/periods.py.
"""

from fastapi import APIRouter, Depends

from app.models import User
from app.periods import PERIODS, TEACHING_DAYS, WEEKDAY_NAMES
from app.schemas import PeriodOut, PeriodsOut
from app.security import get_current_user

router = APIRouter(prefix="/api/periods", tags=["timetable"])


@router.get("", response_model=PeriodsOut)
def list_periods(_: User = Depends(get_current_user)) -> PeriodsOut:
    """Teaching days and periods, lunch break included (endpoint 26)."""
    return PeriodsOut(
        days=[WEEKDAY_NAMES[d] for d in TEACHING_DAYS],
        periods=[
            PeriodOut(period=p.code, label=p.label, start=p.start.strftime("%H:%M"),
                      end=p.end.strftime("%H:%M"), bookable=p.bookable)
            for p in PERIODS
        ],
    )
