"""Settings for the backend, read from the .env file.

Every secret or machine-specific value (database password, keys) lives in
.env, so the code itself never contains passwords and works on every
team member's laptop without changes.
"""

from datetime import timedelta, timezone
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The .env file sits in the backend/ folder, next to requirements.txt.
# Using an absolute path means it is found no matter which folder you
# start the server from.
BACKEND_DIR = Path(__file__).resolve().parent.parent

# India Standard Time. India has no daylight saving, so a fixed +05:30
# offset is always correct and needs no extra time-zone package on Windows.
IST = timezone(timedelta(hours=5, minutes=30), name="IST")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str
    # Separate database used only by the automated tests, so running the
    # tests never touches your real data.
    test_database_url: str | None = None

    jwt_secret: str
    jwt_expire_minutes: int = 480

    device_key: str

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    email_from: str = ""

    # No-show rule (minutes). Kept here so they can be changed in one place.
    no_show_reminder_after: int = 15
    no_show_release_after: int = 10
    # A camera reading older than this counts as "No camera data".
    occupancy_stale_seconds: int = 60
    # Camera readings arrive every few seconds per room, so old ones are
    # deleted after this many days to keep the database small.
    occupancy_keep_days: int = 7

    @field_validator("jwt_secret")
    @classmethod
    def _secret_long_enough(cls, value: str) -> str:
        # A short secret can be guessed, letting someone forge an admin login.
        if len(value) < 32 or value.startswith("change-me"):
            raise ValueError(
                "JWT_SECRET in .env must be a random string of at least 32 characters. "
                "Make one with:  python -c \"import secrets; print(secrets.token_urlsafe(48))\""
            )
        return value

    @field_validator("device_key")
    @classmethod
    def _device_key_long_enough(cls, value: str) -> str:
        # Anyone with this key can send fake camera readings.
        if len(value) < 16 or value.startswith("change-me"):
            raise ValueError(
                "DEVICE_KEY in .env must be a random string of at least 16 characters. "
                "Make one with:  python -c \"import secrets; print(secrets.token_urlsafe(24))\""
            )
        return value


settings = Settings()
