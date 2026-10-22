"""The no-show check: free rooms that were booked but nobody came to.

Every minute (see scheduler.py), for each booking that is in progress:

1. NO_SHOW_REMINDER_AFTER minutes (15) after it started, if the camera
   proves nobody has been in the room since the start, the teacher who
   booked it and the class CR get a "no_show_reminder". They can answer
   Keep or Release (endpoint 18). It is sent only once.
2. If nobody answers and the room is STILL empty NO_SHOW_RELEASE_AFTER
   minutes (10) after the reminder, the booking is "released", the change
   log records it with done_by = NULL (the system did it), and both are
   told with "booking_released".

"The camera proves nobody was there" is strict, because releasing a class
that is actually happening would be far worse than keeping an empty room:
- the room has a camera and the no-show check is enabled for it,
- readings kept arriving the whole time (no gap longer than
  OCCUPANCY_STALE_SECONDS, including right after the start and up to now),
- every reading was "online" and said "not detected".
Missing, late, offline or mixed camera data means: do nothing.

The decisions are plain functions that take "now" as an argument, so the
tests can check every case without waiting real minutes.
"""

import datetime as dt
import logging
from collections.abc import Callable, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models import (
    ACTIVE_STATUSES,
    Booking,
    BookingStatus,
    CameraStatus,
    ChangeAction,
    ChangeLog,
    NotificationType,
    OccupancyReading,
    Room,
    User,
)
from app.notify import Email, describe_slot, notify, send_emails
from app.timeutil import hhmm, now_ist

log = logging.getLogger("roomsync.no_show")

REMIND = "remind"
RELEASE = "release"


# ---------------------------------------------------------------------------
# Decisions (no database, no clock)
# ---------------------------------------------------------------------------

def room_stayed_empty(readings: Iterable[OccupancyReading], start: dt.datetime,
                      end: dt.datetime) -> bool:
    """True only if the camera data proves nobody was in the room from start to end."""
    window = sorted((r for r in readings if start <= r.time <= end), key=lambda r: r.time)
    if not window:
        return False
    max_gap = dt.timedelta(seconds=settings.occupancy_stale_seconds)
    previous = start
    for reading in window:
        if reading.camera_status != CameraStatus.online or reading.people_detected is not False:
            return False
        if reading.time - previous > max_gap:
            return False
        previous = reading.time
    return end - previous <= max_gap


def decide(booking: Booking, room: Room, readings: Iterable[OccupancyReading],
           now: dt.datetime) -> str | None:
    """What the no-show check should do with this booking right now.

    Returns REMIND, RELEASE or None (leave it alone).
    """
    if booking.status.value not in ACTIVE_STATUSES:
        return None
    if not room.no_show_enabled or not room.has_camera:
        return None
    if booking.no_show_kept_at is not None:
        return None   # the teacher or CR said "keep"
    if not booking.start_at <= now < booking.end_at:
        return None   # not in progress

    if booking.reminder_sent_at is None:
        remind_at = booking.start_at + dt.timedelta(minutes=settings.no_show_reminder_after)
        if now >= remind_at and room_stayed_empty(readings, booking.start_at, now):
            return REMIND
        return None

    release_at = booking.reminder_sent_at + dt.timedelta(minutes=settings.no_show_release_after)
    if now >= release_at and room_stayed_empty(readings, booking.start_at, now):
        return RELEASE
    return None


# ---------------------------------------------------------------------------
# Actions (change the database; the caller commits and sends the emails)
# ---------------------------------------------------------------------------

def label(booking: Booking) -> str:
    """'CSE-101 on 3 Nov, 15:00-16:00 (Extra class - DBMS)'"""
    return f"{describe_slot(booking.room_id, booking.start_at, booking.end_at)} ({booking.purpose})"


def send_reminder(db: Session, booking: Booking, now: dt.datetime) -> list[Email]:
    booking.reminder_sent_at = now
    release_at = now + dt.timedelta(minutes=settings.no_show_release_after)
    what = label(booking)
    ask = (f"Is the room still needed? Answer Keep or Release. If there is no answer "
           f"and the room stays empty, it will be released at {hhmm(release_at)}.")
    _, emails = notify(
        db, booking, None, NotificationType.no_show_reminder,
        teacher_message=f"No one has been detected in {what} since it started. {ask}",
        cr_message=f"No one has been detected in your class's booking of {what} "
                   f"since it started. {ask}",
    )
    return emails


def release(db: Session, booking: Booking, by: User | None) -> tuple[list[str], list[Email]]:
    """Free the room. by is None when the no-show check does it automatically."""
    what = label(booking)
    booking.status = BookingStatus.released
    if by is None:
        reason = (f"No people detected for {settings.no_show_reminder_after} minutes after the "
                  f"start, and the no-show reminder was not answered.")
        why = "because no one was detected in the room and the no-show reminder was not answered"
    else:
        reason = f"Released by {by.name} in answer to the no-show reminder."
        why = f"by {by.name} in answer to the no-show reminder"
    db.add(ChangeLog(booking_id=booking.id, action=ChangeAction.release,
                     done_by=by.id if by else None, reason=reason, details=what))
    return notify(
        db, booking, by, NotificationType.booking_released,
        teacher_message=f"Your booking of {what} was released {why}.",
        cr_message=f"Your class's booking of {what} was released {why}.",
    )


# ---------------------------------------------------------------------------
# The every-minute job
# ---------------------------------------------------------------------------

def run_no_show_check(now: dt.datetime | None = None,
                      session_factory: Callable[[], Session] = SessionLocal) -> None:
    """Check every booking in progress once. Called every minute by the scheduler."""
    now = now or now_ist()
    earliest = now - dt.timedelta(minutes=settings.no_show_reminder_after)
    emails: list[Email] = []
    with session_factory() as db:
        bookings = db.scalars(
            select(Booking).join(Room).where(
                Booking.status.in_(ACTIVE_STATUSES),
                Booking.start_at <= earliest,
                Booking.end_at > now,
                Booking.no_show_kept_at.is_(None),
                Room.no_show_enabled.is_(True),
                Room.camera_stream.is_not(None),
            )
        ).all()
        for booking in bookings:
            readings = db.scalars(select(OccupancyReading).where(
                OccupancyReading.room_id == booking.room_id,
                OccupancyReading.time >= booking.start_at,
                OccupancyReading.time <= now,
            )).all()
            action = decide(booking, booking.room, readings, now)
            try:
                if action == REMIND:
                    emails += send_reminder(db, booking, now)
                elif action == RELEASE:
                    emails += release(db, booking, None)[1]
                else:
                    continue
                db.commit()
                log.info("No-show check: %s booking %s", action, booking.id)
            except Exception:
                # One bad booking must not stop the check for the others.
                db.rollback()
                log.exception("No-show check failed for booking %s", booking.id)
    send_emails(emails)
