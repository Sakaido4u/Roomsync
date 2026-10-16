"""Database connection.

`engine` is the connection to PostgreSQL. `SessionLocal` hands out a
session (a short conversation with the database) for each request, and
`get_db` makes sure that session is always closed afterwards, even if
the request fails.
"""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    """Every table class in models.py inherits from this."""


def make_engine(url: str):
    # pool_pre_ping checks a connection still works before using it, which
    # avoids errors after PostgreSQL restarts or your laptop sleeps.
    return create_engine(url, pool_pre_ping=True)


engine = make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one database session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
