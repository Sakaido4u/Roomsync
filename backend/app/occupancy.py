"""Turning camera readings into the dashboard's occupancy value.

The camera program sends a reading every few seconds (endpoint 20). The
dashboard only ever needs the LATEST reading per room, converted to one of:
    people_detected / not_detected / no_data
"no_data" covers: no reading yet, camera offline, or the last reading is
older than OCCUPANCY_STALE_SECONDS (camera program stopped or PC crashed).
"""

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import CameraStatus, OccupancyReading
from app.timeutil import now_ist


@dataclass
class Occupancy:
    occupancy: str              # people_detected / not_detected / no_data
    head_count: int | None
    last_reading_at: dt.datetime | None


NO_DATA = Occupancy("no_data", None, None)


def latest_readings(db: Session, room_ids: list[str]) -> dict[str, OccupancyReading]:
    """Newest reading for each room, in one database query."""
    if not room_ids:
        return {}
    # Step 1: for each room, find the time of its newest reading.
    newest = (
        select(OccupancyReading.room_id, func.max(OccupancyReading.time).label("newest"))
        .where(OccupancyReading.room_id.in_(room_ids))
        .group_by(OccupancyReading.room_id)
        .subquery()
    )
    # Step 2: fetch the readings that match those (room, time) pairs.
    rows = db.scalars(
        select(OccupancyReading)
        .join(newest, (OccupancyReading.room_id == newest.c.room_id)
              & (OccupancyReading.time == newest.c.newest))
        .order_by(OccupancyReading.id)
    ).all()
    return {r.room_id: r for r in rows}


def to_occupancy(reading: OccupancyReading | None, now: dt.datetime | None = None) -> Occupancy:
    if reading is None:
        return NO_DATA
    now = now or now_ist()
    too_old = now - reading.time > dt.timedelta(seconds=settings.occupancy_stale_seconds)
    if too_old or reading.camera_status == CameraStatus.offline or reading.people_detected is None:
        return Occupancy("no_data", None, reading.time)
    if reading.people_detected:
        return Occupancy("people_detected", reading.head_count, reading.time)
    return Occupancy("not_detected", reading.head_count or 0, reading.time)
