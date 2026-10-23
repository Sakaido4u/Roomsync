"""Subjects, who teaches what, and the class list (contract endpoints 27-32)."""

import datetime as dt

import pytest
from sqlalchemy import select

from app.models import SchoolClass, Subject, SubjectType, TeachingAssignment


@pytest.fixture()
def subjects(db, world):
    db.add_all([
        Subject(code="BCS702", title="Parallel Computing", type=SubjectType.ipcc,
                credits=4, department="CSE"),
        Subject(code="BCS703", title="Cryptography & Network Security",
                type=SubjectType.pcc, credits=4, department="CSE"),
    ])
    db.commit()


def assign(client, headers, **fields):
    body = {"teacher": "T1", "subject_code": "BCS702", "class_id": "CSE-7A", **fields}
    return client.post("/api/teaching", json=body, headers=headers)


# --- Subjects (27, 29) ------------------------------------------------------

def test_everyone_can_list_subjects(client, login, subjects):
    r = client.get("/api/subjects", headers=login("student"))
    assert r.status_code == 200, r.text
    assert r.json()[0] == {"code": "BCS702", "title": "Parallel Computing", "type": "IPCC",
                           "credits": 4, "department": "CSE"}
    assert [s["code"] for s in r.json()] == ["BCS702", "BCS703"]


def test_admin_adds_a_subject(client, login, world, db):
    r = client.post("/api/subjects", headers=login("admin"), json={
        "code": "bcs786", "title": "Major Project Phase-II", "type": "PROJ",
        "credits": 6, "department": "CSE"})
    assert r.status_code == 201, r.text
    assert r.json()["code"] == "BCS786"      # codes are stored in capitals
    assert db.get(Subject, "BCS786").type == SubjectType.proj


def test_adding_an_existing_subject_is_a_conflict(client, login, subjects):
    r = client.post("/api/subjects", headers=login("admin"), json={
        "code": "BCS702", "title": "Again", "type": "IPCC", "credits": 4,
        "department": "CSE"})
    assert r.status_code == 409
    assert r.json()["error"] == "conflict"


@pytest.mark.parametrize("change", [
    {"type": "LAB"}, {"credits": -1}, {"code": "BCS 702"}, {"title": ""}])
def test_bad_subject_is_refused(client, login, world, change):
    body = {"code": "BCS799", "title": "X", "type": "PCC", "credits": 3, "department": "CSE"}
    r = client.post("/api/subjects", headers=login("admin"), json={**body, **change})
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_input"


@pytest.mark.parametrize("who", ["teacher", "student"])
def test_only_admins_add_subjects(client, login, world, who):
    r = client.post("/api/subjects", headers=login(who), json={
        "code": "BCS799", "title": "X", "type": "PCC", "credits": 3, "department": "CSE"})
    assert r.status_code == 403


# --- Who teaches what (30-32) -----------------------------------------------

def test_admin_records_an_assignment_by_college_id(client, login, world, subjects):
    r = assign(client, login("admin"))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["teacher"] == {"user_id": world["teacher"].id, "college_id": "T1",
                               "name": "Prof. A", "initials": None}
    assert body["subject"]["title"] == "Parallel Computing"
    assert (body["class_id"], body["batch"]) == ("CSE-7A", None)


def test_admin_records_an_assignment_by_user_id_with_a_batch(client, login, world, subjects):
    r = client.post("/api/teaching", headers=login("admin"), json={
        "teacher_id": world["teacher2"].id, "subject_code": "BCS702", "class_id": "CSE-7A",
        "batch": "A1"})
    assert r.status_code == 201, r.text
    assert (r.json()["teacher"]["college_id"], r.json()["batch"]) == ("T2", "A1")


def test_same_assignment_twice_is_a_conflict(client, login, world, subjects):
    assert assign(client, login("admin")).status_code == 201
    r = assign(client, login("admin"))
    assert r.status_code == 409
    # A batch is a different assignment from the whole class.
    assert assign(client, login("admin"), batch="A1").status_code == 201
    assert assign(client, login("admin"), batch="A1").status_code == 409


@pytest.mark.parametrize("change, status, words", [
    ({"teacher": "S1"}, 400, "is not an active teacher"),
    ({"teacher": "NOBODY"}, 404, "NOBODY does not exist"),
    ({"subject_code": "XYZ123"}, 404, "Subject XYZ123 does not exist"),
    ({"class_id": "CSE-9Z"}, 404, "Class CSE-9Z does not exist"),
    ({"teacher_id": 1}, 400, "exactly one of teacher"),     # both given
    ({"teacher": None}, 400, "exactly one of teacher"),     # neither given
])
def test_bad_assignment_is_refused(client, login, world, subjects, change, status, words):
    r = assign(client, login("admin"), **change)
    assert r.status_code == status, r.text
    assert words in r.json()["message"]


@pytest.mark.parametrize("who", ["teacher", "student", "super_admin"])
def test_only_admins_record_assignments(client, login, world, subjects, who):
    assert assign(client, login(who)).status_code == 403


def test_list_assignments_with_filters(client, login, world, subjects, db):
    db.add(SchoolClass(class_id="CSE-7B", name="CSE 7B", department="CSE"))
    db.commit()
    admin = login("admin")
    assign(client, admin)
    assign(client, admin, class_id="CSE-7B")
    assign(client, admin, teacher="T2", subject_code="BCS703")

    everyone = client.get("/api/teaching", headers=login("student")).json()
    assert len(everyone) == 3
    mine = client.get("/api/teaching?teacher=T1", headers=login("teacher")).json()
    assert [(a["subject"]["code"], a["class_id"]) for a in mine] == [
        ("BCS702", "CSE-7A"), ("BCS702", "CSE-7B")]
    seven_a = client.get("/api/teaching?class_id=CSE-7A", headers=admin).json()
    assert [a["subject"]["code"] for a in seven_a] == ["BCS702", "BCS703"]


def test_admin_removes_an_assignment(client, login, world, subjects, db):
    teaching_id = assign(client, login("admin")).json()["teaching_id"]
    assert client.delete(f"/api/teaching/{teaching_id}",
                         headers=login("teacher")).status_code == 403
    r = client.delete(f"/api/teaching/{teaching_id}", headers=login("admin"))
    assert r.status_code == 200, r.text
    assert r.json()["teaching_id"] == teaching_id
    db.expire_all()
    assert db.scalars(select(TeachingAssignment)).all() == []
    assert client.delete(f"/api/teaching/{teaching_id}",
                         headers=login("admin")).status_code == 404


# --- Class list (28) --------------------------------------------------------

def test_class_list_shows_sheet_details(client, login, world, db):
    cls = db.get(SchoolClass, "CSE-7A")
    cls.semester_label = "VII-A"
    cls.home_room_id = "CSE-101"
    cls.strength = 64
    cls.wef_date = dt.date(2026, 7, 20)
    cls.class_teacher_id = world["teacher"].id
    db.add(SchoolClass(class_id="CSE-5B", name="CSE 5B", department="CSE"))
    db.commit()

    r = client.get("/api/classes", headers=login("student"))
    assert r.status_code == 200, r.text
    assert r.json() == [
        {"class_id": "CSE-5B", "name": "CSE 5B", "department": "CSE",
         "semester_label": None, "home_room_id": None, "strength": None, "wef_date": None,
         "class_teacher": None},
        {"class_id": "CSE-7A", "name": "CSE 7A", "department": "CSE",
         "semester_label": "VII-A", "home_room_id": "CSE-101", "strength": 64,
         "wef_date": "2026-07-20",
         "class_teacher": {"user_id": world["teacher"].id, "name": "Prof. A"}},
    ]
