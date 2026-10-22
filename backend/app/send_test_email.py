"""Send one test email, to check the SMTP settings in .env.

Run from the backend folder, with the venv active:

    python -m app.send_test_email you@example.com

Unlike the real notifications (which only log problems so a mail server
hiccup never breaks the dashboard), this prints exactly what went wrong.
"""

import smtplib
import sys
from email.message import EmailMessage

from app.config import settings
from app.notify import email_enabled

HINTS = {
    smtplib.SMTPAuthenticationError: (
        "Gmail refused the login. Check that SMTP_USER is the full Gmail address and "
        "SMTP_PASSWORD is the 16-letter App Password (not your normal Gmail password), "
        "and that 2-Step Verification is on for that account."
    ),
    smtplib.SMTPConnectError: "Could not connect. Check SMTP_HOST and SMTP_PORT.",
    TimeoutError: "The mail server did not answer. Check your internet connection, "
                  "SMTP_HOST and SMTP_PORT (Gmail: smtp.gmail.com, 587).",
    ConnectionRefusedError: "The connection was refused. Check SMTP_HOST and SMTP_PORT.",
}


def main() -> int:
    if len(sys.argv) != 2 or "@" not in sys.argv[1]:
        print("Usage: python -m app.send_test_email you@example.com")
        return 2
    to = sys.argv[1]

    if not email_enabled():
        print("Email is not set up: fill in SMTP_HOST, SMTP_USER and SMTP_PASSWORD in "
              "backend/.env, then try again.")
        return 1

    msg = EmailMessage()
    msg["From"] = settings.email_from or settings.smtp_user
    msg["To"] = to
    msg["Subject"] = "RoomSync: test email"
    msg.set_content("If you can read this, RoomSync can send notification emails.")

    print(f"Sending a test email to {to} through {settings.smtp_host}:{settings.smtp_port} "
          f"as {settings.smtp_user} ...")
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
            smtp.starttls()
            smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(msg)
    except Exception as exc:  # report every kind of failure in plain words
        hint = next((h for kind, h in HINTS.items() if isinstance(exc, kind)), None)
        print(f"Failed: {type(exc).__name__}: {exc}")
        if hint:
            print(hint)
        return 1

    print("Sent. Check the inbox (and the spam folder) of", to)
    return 0


if __name__ == "__main__":
    sys.exit(main())
