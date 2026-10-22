"""Choosing a class's CR (contract endpoint 7)."""

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import Role, SchoolClass, User
from tests.conftest import PASSWORD_HASH


@pytest.fixture()
def classes(db, world):
    """CSE-7A's class teacher is Prof. A; a second class CSE-5B has its own student."""
    db.get(SchoolClass, "CSE-7A").class_teacher_id = world["teacher"].id
    db.add(SchoolClass(class_id="CSE-5B", name="CSE 5B", department="CSE",
                       class_teacher_id=world["teacher2"].id))
    db.flush()
    students = {
        "s1": world["student"],
        "s2": User(college_id="S2", name="Student Two", email="s2@example.com",
                   password_hash=PASSWORD_HASH, role=Role.student, department="CSE",
                   class_id="CSE-7A"),
        "other": User(college_id="S3", name="Student Five-B", email="s3@example.com",
                      password_hash=PASSWORD_HASH, role=Role.student, department="CSE",
                      class_id="CSE-5B"),
    }
    db.add_all([students["s2"], students["other"]])
    db.commit()
    return students


def set_cr(client, headers, student_id, class_id="CSE-7A"):
    return client.put(f"/api/classes/{class_id}/cr", json={"student_id": student_id},
                      headers=headers)


def crs(db, class_id="CSE-7A"):
    db.expire_all()
    return [u.id for u in db.query(User).filter_by(class_id=class_id, is_cr=True)]


def test_class_teacher_chooses_cr(client, login, db, classes):
    r = set_cr(client, login("teacher"), classes["s1"].id)
    assert r.status_code == 200, r.text
    assert r.json() == {"class_id": "CSE-7A",
                        "cr": {"user_id": classes["s1"].id, "name": "Student One"}}
    assert crs(db) == [classes["s1"].id]


def test_cr_shows_on_the_students_account(client, login, classes):
    set_cr(client, login("teacher"), classes["s1"].id)
    me = client.get("/api/auth/me", headers=login("student")).json()
    assert me["is_cr"] is True


def test_new_cr_replaces_old_one(client, login, db, classes):
    set_cr(client, login("teacher"), classes["s1"].id)
    r = set_cr(client, login("teacher"), classes["s2"].id)
    assert r.status_code == 200
    assert crs(db) == [classes["s2"].id]


def test_choosing_the_same_cr_again_is_fine(client, login, db, classes):
    set_cr(client, login("teacher"), classes["s1"].id)
    assert set_cr(client, login("teacher"), classes["s1"].id).status_code == 200
    assert crs(db) == [classes["s1"].id]


def test_null_clears_the_cr(client, login, db, classes):
    set_cr(client, login("teacher"), classes["s1"].id)
    r = set_cr(client, login("teacher"), None)
    assert r.status_code == 200
    assert r.json() == {"class_id": "CSE-7A", "cr": None}
    assert crs(db) == []


def test_leaving_out_student_id_does_not_clear(client, login, db, classes):
    set_cr(client, login("teacher"), classes["s1"].id)
    r = client.put("/api/classes/CSE-7A/cr", json={}, headers=login("teacher"))
    assert r.status_code == 400
    assert crs(db) == [classes["s1"].id]


def test_other_classes_keep_their_cr(client, login, db, classes):
    set_cr(client, login("teacher2"), classes["other"].id, class_id="CSE-5B")
    set_cr(client, login("teacher"), classes["s1"].id)
    assert crs(db, "CSE-5B") == [classes["other"].id]


@pytest.mark.parametrize("who", ["teacher2", "admin", "super_admin", "student"])
def test_only_the_class_teacher_can_choose(client, login, db, classes, who):
    r = set_cr(client, login(who), classes["s1"].id)
    assert r.status_code == 403
    assert r.json()["error"] == "forbidden"
    assert crs(db) == []


def test_cr_must_be_a_student_of_that_class(client, login, db, classes, world):
    r = set_cr(client, login("teacher"), classes["other"].id)
    assert r.status_code == 400
    assert "is not in class CSE-7A" in r.json()["message"]
    r = set_cr(client, login("teacher"), world["teacher2"].id)
    assert r.status_code == 400
    assert "is not an active student" in r.json()["message"]
    assert crs(db) == []


def test_unknown_class_or_student(client, login, classes):
    assert set_cr(client, login("teacher"), classes["s1"].id, class_id="NOPE").status_code == 404
    assert set_cr(client, login("teacher"), 99999).status_code == 404


def test_needs_login(client, classes):
    assert set_cr(client, {}, classes["s1"].id).status_code == 401


def test_database_refuses_two_crs_in_one_class(db, classes):
    classes["s1"].is_cr = True
    classes["s2"].is_cr = True
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
