"""Granting and removing admin rights (contract endpoints 5 and 6)."""

import pytest

from app.models import Role, User

NEW_ROOM = {"room_id": "CSE-201", "name": "Classroom 201", "type": "classroom",
            "building": "Main", "floor": 2, "capacity": 60, "department": "CSE"}


def grant(client, headers, user_id):
    return client.post("/api/admin/admins", json={"user_id": user_id}, headers=headers)


def revoke(client, headers, user_id):
    return client.delete(f"/api/admin/admins/{user_id}", headers=headers)


def test_super_admin_makes_teacher_an_admin(client, login, world, db):
    r = grant(client, login("super_admin"), world["teacher"].id)
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "admin"
    assert r.json()["user_id"] == world["teacher"].id
    db.expire_all()
    assert db.get(User, world["teacher"].id).role == Role.admin


def test_new_admin_rights_work_with_existing_login(client, login, world):
    teacher = login("teacher")   # logged in BEFORE becoming an admin
    assert client.post("/api/rooms", json=NEW_ROOM, headers=teacher).status_code == 403
    grant(client, login("super_admin"), world["teacher"].id)
    assert client.post("/api/rooms", json=NEW_ROOM, headers=teacher).status_code == 201


def test_removed_admin_loses_rights_immediately(client, login, world, db):
    admin = login("admin")       # still holds a token issued while an admin
    r = revoke(client, login("super_admin"), world["admin"].id)
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "teacher"
    r = client.post("/api/rooms", json=NEW_ROOM, headers=admin)
    assert r.status_code == 403
    assert r.json()["error"] == "forbidden"


def test_former_admin_can_still_teach(client, login, world):
    revoke(client, login("super_admin"), world["admin"].id)
    r = client.get("/api/bookings/mine", headers=login("admin"))
    assert r.status_code == 200


@pytest.mark.parametrize("who, message", [
    ("student", "Only teachers can be made admins"),
    ("super_admin", "Only teachers can be made admins"),
    ("admin", "already an admin"),
])
def test_only_teachers_can_be_made_admins(client, login, world, who, message):
    r = grant(client, login("super_admin"), world[who].id)
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_input"
    assert message in r.json()["message"]


def test_inactive_teacher_cannot_be_made_admin(client, login, world, db):
    world["teacher2"].is_active = False
    db.commit()
    r = grant(client, login("super_admin"), world["teacher2"].id)
    assert r.status_code == 400


@pytest.mark.parametrize("who", ["teacher", "student", "super_admin"])
def test_can_only_remove_rights_from_admins(client, login, world, db, who):
    r = revoke(client, login("super_admin"), world[who].id)
    assert r.status_code == 400
    assert "is not an admin" in r.json()["message"]
    db.expire_all()
    assert db.get(User, world[who].id).role == world[who].role


def test_unknown_user(client, login, world):
    assert grant(client, login("super_admin"), 99999).status_code == 404
    assert revoke(client, login("super_admin"), 99999).status_code == 404


@pytest.mark.parametrize("who", ["admin", "teacher", "student"])
def test_only_super_admin_can_change_admin_rights(client, login, world, db, who):
    headers = login(who)
    assert grant(client, headers, world["teacher2"].id).status_code == 403
    assert revoke(client, headers, world["admin"].id).status_code == 403
    db.expire_all()
    assert db.get(User, world["teacher2"].id).role == Role.teacher
    assert db.get(User, world["admin"].id).role == Role.admin


def test_admin_cannot_make_themselves_super_admin_or_admin(client, login, world):
    # A teacher trying to promote themselves gets nowhere.
    r = grant(client, login("teacher"), world["teacher"].id)
    assert r.status_code == 403


def test_needs_login(client, world):
    assert grant(client, {}, world["teacher"].id).status_code == 401
    assert revoke(client, {}, world["admin"].id).status_code == 401


def test_missing_user_id(client, login, world):
    r = client.post("/api/admin/admins", json={}, headers=login("super_admin"))
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_input"
