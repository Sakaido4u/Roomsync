"""The course list (API contract endpoints 27 and 29).

Everyone can read it (students see it under their timetable); only admins
add subjects.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import ApiError
from app.models import Role, Subject, SubjectType, User
from app.schemas import SubjectIn, SubjectOut
from app.security import get_current_user, require_roles

router = APIRouter(prefix="/api/subjects", tags=["timetable"])


@router.get("", response_model=list[SubjectOut])
def list_subjects(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[SubjectOut]:
    """All subjects, sorted by code (endpoint 27)."""
    return [SubjectOut.of(s) for s in db.scalars(select(Subject).order_by(Subject.code))]


@router.post("", response_model=SubjectOut, status_code=201)
def add_subject(
    body: SubjectIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(Role.admin)),
) -> SubjectOut:
    """Add a subject to the course list (endpoint 29, admin only)."""
    code = body.code.upper()
    if db.get(Subject, code) is not None:
        raise ApiError(409, "conflict", f"Subject {code} already exists.")
    subject = Subject(code=code, title=body.title.strip(), type=SubjectType(body.type),
                      credits=body.credits, department=body.department)
    db.add(subject)
    db.commit()
    return SubjectOut.of(subject)
