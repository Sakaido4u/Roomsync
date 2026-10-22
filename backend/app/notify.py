"""Creating notifications and sending their email copies.

When an admin changes a booking, two people may need to know:
- the teacher who made the booking, and
- the CR of the booking's class, if the booking is for a class that has one.

Each gets a row in the notifications table (shown on the dashboard bell)
and, when SMTP is set up in .env, an email with the same message. Emails
are sent after the reply has gone back, so a slow mail server never makes
the dashboard wait, and a failed email never undoes the booking change.
"""

import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Booking, Notification, NotificationType, Role, User
from app.timeutil import hhmm, to_ist

log = logging.getLogger("roomsync.notify")


@dataclass
class Email:
    to: str
    subject: str
    body: str


@dataclass
class Recipient:
    user: User
    label: str          # how they appear in the "notified" list
    is_cr: bool


def describe_slot(room_id: str, start, end) -> str:
    """'CSE-101 on 3 Nov, 15:00-16:00'"""
    day = to_ist(start)
    return f"{room_id} on {day.day} {day:%b}, {hhmm(start)}-{hhmm(end)}"


def class_cr(db: Session, class_id: str | None) -> User | None:
    if class_id is None:
        return None
    return db.scalar(
        select(User).where(User.class_id == class_id, User.is_cr.is_(True),
                           User.role == Role.student, User.is_active.is_(True))
    )


def recipients_for(db: Session, booking: Booking, actor: User) -> list[Recipient]:
    """Who to tell about a change to this booking. The admin making the change is skipped."""
    people: list[Recipient] = []
    if booking.booked_by.id != actor.id:
        people.append(Recipient(booking.booked_by, booking.booked_by.name, is_cr=False))
    cr = class_cr(db, booking.class_id)
    if cr is not None and cr.id != actor.id:
        people.append(Recipient(cr, f"CR of {booking.class_id}", is_cr=True))
    return people


def notify(
    db: Session,
    booking: Booking,
    actor: User,
    kind: NotificationType,
    teacher_message: str,
    cr_message: str,
) -> tuple[list[str], list[Email]]:
    """Add notification rows (not yet committed) and prepare their emails.

    Returns the "notified" labels for the API reply and the emails to send
    once the change is saved.
    """
    labels: list[str] = []
    emails: list[Email] = []
    subject = {
        NotificationType.booking_overridden: "RoomSync: your booking was taken over",
        NotificationType.booking_rescheduled: "RoomSync: your booking was moved",
        NotificationType.booking_removed: "RoomSync: your booking was removed",
        NotificationType.no_show_reminder: "RoomSync: is your room in use?",
        NotificationType.booking_released: "RoomSync: your booking was released",
    }[kind]
    for person in recipients_for(db, booking, actor):
        message = cr_message if person.is_cr else teacher_message
        db.add(Notification(user_id=person.user.id, booking_id=booking.id, type=kind,
                            message=message))
        labels.append(person.label)
        emails.append(Email(to=person.user.email, subject=subject, body=message))
    return labels, emails


def email_enabled() -> bool:
    return bool(settings.smtp_host and settings.smtp_user and settings.smtp_password)


def send_emails(emails: list[Email]) -> None:
    """Send the email copies. Runs after the reply; problems are logged, never raised."""
    if not emails or not email_enabled():
        return
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
            smtp.starttls()
            smtp.login(settings.smtp_user, settings.smtp_password)
            for email in emails:
                msg = EmailMessage()
                msg["From"] = settings.email_from or settings.smtp_user
                msg["To"] = email.to
                msg["Subject"] = email.subject
                msg.set_content(email.body)
                try:
                    smtp.send_message(msg)
                except smtplib.SMTPException:
                    log.exception("Could not email %s", email.to)
    except (OSError, smtplib.SMTPException):
        log.exception("Could not connect to the mail server %s", settings.smtp_host)
