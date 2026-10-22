"""Shared test setup.

Tests run against a separate database (TEST_DATABASE_URL in .env), so
they can freely delete data without touching your real roomsync database.
Every test starts with empty tables.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.database import Base, get_db, make_engine
from app.init_db import create_tables, drop_tables
from app.main import app
from app.models import Role, Room, RoomType, SchoolClass, User
from app.security import hash_password

PASSWORD = "pass1234"
# Hashing is deliberately slow, so do it once and reuse it for every test user.
PASSWORD_HASH = hash_password(PASSWORD)


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


@pytest.fixture()
def client(engine, db):
    """A fake browser that calls the API, wired to the test database."""
    test_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_db():
        session = test_session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def world(db):
    """A small college: one class, five people, three rooms."""
    cls = SchoolClass(class_id="CSE-7A", name="CSE 7A", department="CSE")
    db.add(cls)
    db.flush()

    def person(college_id, name, role, **extra):
        return User(college_id=college_id, name=name, email=f"{college_id.lower()}@example.com",
                    password_hash=PASSWORD_HASH, role=role, department="CSE", **extra)

    people = {
        "teacher": person("T1", "Prof. A", Role.teacher),
        "teacher2": person("T2", "Prof. B", Role.teacher),
        "admin": person("A1", "Dr. HOD", Role.admin),
        "student": person("S1", "Student One", Role.student, class_id="CSE-7A"),
        "super_admin": person("SA1", "Principal Office", Role.super_admin),
    }
    db.add_all(people.values())
    db.add_all([
        Room(room_id="CSE-101", name="Classroom 101", type=RoomType.classroom,
             building="Main", capacity=60, department="CSE"),
        Room(room_id="CSE-102", name="Classroom 102", type=RoomType.classroom,
             building="Main", capacity=60, department="CSE"),
        Room(room_id="LAB-1", name="Lab 1", type=RoomType.lab,
             building="Main", capacity=40, department="CSE"),
    ])
    db.commit()
    return people


@pytest.fixture()
def login(client, world):
    """login("teacher") -> headers to send as that person."""

    def _login(who: str) -> dict:
        r = client.post("/api/auth/login",
                        json={"college_id": world[who].college_id, "password": PASSWORD})
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['token']}"}

    return _login
