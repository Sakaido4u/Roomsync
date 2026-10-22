"""Listing people (endpoint 24) and my classes (endpoint 25)."""

import pytest

from app.models import Role, SchoolClass, User
from tests.conftest import PASSWORD_HASH


# --- 24. User list -------------------------------------------------------------

@pytest.mark.parametrize("who", ["admin", "super_admin"])
def test_admins_can_list_users(client, login, world, who):
    r = client.get("/api/users", headers=login(who))
    assert r.status_code == 200, r.text
    names = [u["name"] for u in r.json()]
    assert names == sorted(names)
    assert len(names) == 5
    assert set(r.json()[0]) == {"user_id", "college_id", "name", "role", "department"}


def test_filter_by_role(client, login, world):
    r = client.get("/api/users?role=teacher", headers=login("super_admin"))
    assert [u["college_id"] for u in r.json()] == ["T1", "T2"]


def test_inactive_users_are_left_out(client, login, world, db):
    world["teacher2"].is_active = False
    db.commit()
    r = client.get("/api/users?role=teacher", headers=login("admin"))
    assert [u["college_id"] for u in r.json()] == ["T1"]


def test_bad_role_filter(client, login, world):
    r = client.get("/api/users?role=wizard", headers=login("admin"))
    assert r.status_code == 400


@pytest.mark.parametrize("who", ["teacher", "student"])
def test_others_cannot_list_users(client, login, world, who):
    assert client.get("/api/users", headers=login(who)).status_code == 403


# --- 25. My classes --------------------------------------------------------------

def test_class_teacher_sees_class_with_students(client, login, world, db):
    db.get(SchoolClass, "CSE-7A").class_teacher_id = world["teacher"].id
    world["student"].is_cr = True
    db.add(User(college_id="S2", name="Aarav", email="s2@example.com", password_hash=PASSWORD_HASH,
                role=Role.student, department="CSE", class_id="CSE-7A"))
    db.commit()

    r = client.get("/api/classes/mine", headers=login("teacher"))
    assert r.status_code == 200, r.text
    [cls] = r.json()
    assert (cls["class_id"], cls["name"], cls["department"]) == ("CSE-7A", "CSE 7A", "CSE")
    assert [(s["name"], s["is_cr"]) for s in cls["students"]] == [
        ("Aarav", False), ("Student One", True)]


def test_not_a_class_teacher_gets_empty_list(client, login, world):
    r = client.get("/api/classes/mine", headers=login("teacher2"))
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.parametrize("who", ["student", "super_admin"])
def test_students_and_super_admin_cannot_call_it(client, login, world, who):
    assert client.get("/api/classes/mine", headers=login(who)).status_code == 403
