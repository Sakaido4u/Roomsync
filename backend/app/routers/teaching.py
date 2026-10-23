"""Who teaches which subject to which class (API contract endpoints 30-32).

Rows are added automatically by the timetable upload for every entry with
a subject_code, and by admins here for anything not on the timetable.
They decide which subjects a teacher may book extra classes for.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import ApiError, invalid_input, not_found
from app.models import Role, SchoolClass, Subject, TeachingAssignment, User
from app.schemas import TeachingIn, TeachingOut
from app.security import get_current_user, require_roles

router = APIRouter(prefix="/api/teaching", tags=["timetable"])


# ---------------------------------------------------------------------------
# Helpers, also used by the timetable upload
# ---------------------------------------------------------------------------

def find_teacher(db: Session, teacher_id: int | None = None,
                 college_id: str | None = None) -> User:
    """The active teacher (or admin) given by user ID or college ID.

    Raises 404 if nobody has that ID, 400 if they are not an active teacher.
    """
    if college_id is not None:
        user = db.scalar(select(User).where(User.college_id == college_id))
        label = college_id
    else:
        user = db.get(User, teacher_id)
        label = f"User {teacher_id}"
    if user is None:
        raise not_found(f"{label} does not exist.")
    if user.role not in (Role.teacher, Role.admin) or not user.is_active:
        raise invalid_input(f"{label} ({user.name}) is not an active teacher.")
    return user


def find_assignment(db: Session, teacher_id: int, subject_code: str, class_id: str,
                    batch: str | None) -> TeachingAssignment | None:
    return db.scalar(select(TeachingAssignment).where(
        TeachingAssignment.teacher_id == teacher_id,
        TeachingAssignment.subject_code == subject_code,
        TeachingAssignment.class_id == class_id,
        func.coalesce(TeachingAssignment.batch, "") == (batch or ""),
    ))


def record_teaching(db: Session, teacher_id: int, subject_code: str, class_id: str,
                    batch: str | None) -> None:
    """Add the assignment unless it is already recorded."""
    if find_assignment(db, teacher_id, subject_code, class_id, batch) is None:
        db.add(TeachingAssignment(teacher_id=teacher_id, subject_code=subject_code,
                                  class_id=class_id, batch=batch))
        db.flush()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=list[TeachingOut])
def list_teaching(
    teacher: str | None = None,
    class_id: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[TeachingOut]:
    """Who teaches what (endpoint 30), optionally only for one teacher
    (`?teacher=T002`, a college ID) or one class (`?class_id=CSE-7A`)."""
    query = select(TeachingAssignment).join(TeachingAssignment.teacher)
    if teacher is not None:
        query = query.where(User.college_id == teacher)
    if class_id is not None:
        query = query.where(TeachingAssignment.class_id == class_id)
    query = query.order_by(TeachingAssignment.class_id, TeachingAssignment.subject_code,
                           TeachingAssignment.batch.nulls_first(), User.name)
    return [TeachingOut.of(row) for row in db.scalars(query)]


@router.post("", response_model=TeachingOut, status_code=201)
def add_teaching(
    body: TeachingIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(Role.admin)),
) -> TeachingOut:
    """Record that a teacher teaches a subject to a class (endpoint 31, admin only)."""
    teacher = find_teacher(db, body.teacher_id, body.teacher)
    if db.get(Subject, body.subject_code) is None:
        raise not_found(f"Subject {body.subject_code} does not exist.")
    if db.get(SchoolClass, body.class_id) is None:
        raise not_found(f"Class {body.class_id} does not exist.")
    if find_assignment(db, teacher.id, body.subject_code, body.class_id, body.batch):
        raise ApiError(409, "conflict", "This assignment is already recorded.")

    row = TeachingAssignment(teacher_id=teacher.id, subject_code=body.subject_code,
                             class_id=body.class_id, batch=body.batch)
    db.add(row)
    db.commit()
    return TeachingOut.of(row)


@router.delete("/{teaching_id}", response_model=TeachingOut)
def remove_teaching(
    teaching_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(Role.admin)),
) -> TeachingOut:
    """Remove an assignment (endpoint 32, admin only). Timetable classes
    already created are not touched. Replies with the removed row."""
    row = db.get(TeachingAssignment, teaching_id)
    if row is None:
        raise not_found(f"Teaching assignment {teaching_id} does not exist.")
    reply = TeachingOut.of(row)
    db.delete(row)
    db.commit()
    return reply
