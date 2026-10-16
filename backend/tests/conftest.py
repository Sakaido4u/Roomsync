"""Shared test setup.

Tests run against a separate database (TEST_DATABASE_URL in .env), so
they can freely delete data without touching your real roomsync database.
Every test starts with empty tables.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.database import Base, make_engine
from app.init_db import create_tables, drop_tables


@pytest.fixture(scope="session")
def engine():
    if not settings.test_database_url:
        pytest.exit(
            "TEST_DATABASE_URL is not set in .env. Create a roomsync_test database "
            "and add its address (see .env.example).",
            returncode=1,
        )
    if settings.test_database_url == settings.database_url:
        pytest.exit("TEST_DATABASE_URL must be different from DATABASE_URL.", returncode=1)

    eng = make_engine(settings.test_database_url)
    drop_tables(eng)      # start from the current models.py every run
    create_tables(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def db(engine):
    # Empty every table before each test.
    with engine.begin() as conn:
        names = ", ".join(t.name for t in Base.metadata.sorted_tables)
        conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    yield session
    session.close()
