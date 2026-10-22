"""Camera readings (API contract endpoints 20 and 21).

The camera program has no user account. Instead it proves who it is with a
shared key in the "X-Device-Key" header, which must match DEVICE_KEY in .env.
It only ever sends a yes/no and a number, never an image.
"""

import datetime as dt
import secrets

from fastapi import APIRouter, Depends, Header
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.config import IST, settings
from app.database import get_db
from app.errors import invalid_input, not_found, not_logged_in
from app.models import CameraStatus, OccupancyReading, Room, User
from app.occupancy import latest_readings, to_occupancy
from app.schemas import OccupancyIn, OccupancyOut
from app.security import get_current_user
from app.timeutil import now_ist

router = APIRouter(prefix="/api/occupancy", tags=["occupancy"])

# A reading stamped further in the future than this is refused: a camera PC
# with a wrong clock could otherwise make a room look "live" forever.
MAX_CLOCK_AHEAD = dt.timedelta(minutes=2)


def require_device_key(x_device_key: str | None = Header(None)) -> None:
    """Dependency: only the camera program (which knows DEVICE_KEY) gets through."""
    # compare_digest takes the same time whether the key is right or wrong,
    # so an attacker cannot guess the key one character at a time.
    if not x_device_key or not secrets.compare_digest(
        x_device_key.encode("utf-8"), settings.device_key.encode("utf-8")
    ):
        raise not_logged_in("Missing or wrong device key.")


@router.post("", status_code=201, dependencies=[Depends(require_device_key)])
def receive_reading(body: OccupancyIn, db: Session = Depends(get_db)) -> dict:
    """Store one people-detection result from the camera program (endpoint 20)."""
    if db.get(Room, body.room_id) is None:
        raise not_found(f"Room {body.room_id} does not exist.")

    # A time without a zone is taken as India time.
    moment = body.time if body.time.tzinfo else body.time.replace(tzinfo=IST)
    if moment - now_ist() > MAX_CLOCK_AHEAD:
        raise invalid_input("time is in the future. Check the camera PC's clock.")

    people, count = body.people_detected, body.head_count
    if body.camera_status == CameraStatus.offline:
        # Whatever else was sent, an offline camera knows nothing.
        people, count = None, None
    else:
        if people is None:
            raise invalid_input("people_detected is required when the camera is online.")
        if not people and count:
            raise invalid_input("head_count must be 0 when no people are detected.")
        if people and count == 0:
            raise invalid_input("head_count cannot be 0 when people are detected.")
        if not people:
            count = 0

    db.add(OccupancyReading(room_id=body.room_id, time=moment, people_detected=people,
                            head_count=count, camera_status=body.camera_status))

    # Housekeeping: drop this room's readings older than OCCUPANCY_KEEP_DAYS.
    cutoff = now_ist() - dt.timedelta(days=settings.occupancy_keep_days)
    db.execute(delete(OccupancyReading).where(OccupancyReading.room_id == body.room_id,
                                              OccupancyReading.time < cutoff))
    db.commit()
    return {"received": True}


@router.get("/{room_id}", response_model=OccupancyOut)
def latest_for_room(
    room_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> OccupancyOut:
    """The latest reading for one room (endpoint 21). Old or offline readings give no_data."""
    if db.get(Room, room_id) is None:
        raise not_found(f"Room {room_id} does not exist.")
    occ = to_occupancy(latest_readings(db, [room_id]).get(room_id))
    return OccupancyOut(room_id=room_id, occupancy=occ.occupancy,
                        head_count=occ.head_count, last_reading_at=occ.last_reading_at)
