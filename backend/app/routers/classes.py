"""Choosing a class's CR (API contract endpoint 7).

A CR (class representative) is a student who gets notifications about
their class's bookings. Only the class's own class teacher
(classes.class_teacher_id) can choose them. A class has at most one CR:
choosing a new one clears the old one, and null clears it. PostgreSQL also
enforces "one CR per class" (see models.User).
"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import forbidden, invalid_input, not_found
from app.models import Role, SchoolClass, User
from app.schemas import ClassCrIn, ClassCrOut, ClassStudent, MyClassOut, PersonRef
from app.security import get_current_user, require_roles

router = APIRouter(prefix="/api/classes", tags=["classes"])


@router.get("/mine", response_model=list[MyClassOut])
def my_classes(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(Role.teacher, Role.admin)),
) -> list[MyClassOut]:
    """Classes I am class teacher of, with their students and CR (endpoint 25).

    An empty list means the caller is not a class teacher.
    """
    classes = db.scalars(select(SchoolClass).where(SchoolClass.class_teacher_id == user.id)
                         .order_by(SchoolClass.class_id)).all()
    result = []
    for school_class in classes:
        students = db.scalars(select(User).where(
            User.class_id == school_class.class_id, User.role == Role.student,
            User.is_active.is_(True)).order_by(User.name)).all()
        result.append(MyClassOut(
            class_id=school_class.class_id, name=school_class.name,
            department=school_class.department,
            students=[ClassStudent(user_id=s.id, college_id=s.college_id, name=s.name,
                                   is_cr=s.is_cr) for s in students],
        ))
    return result


@router.put("/{class_id}/cr", response_model=ClassCrOut)
def set_class_cr(
    class_id: str,
    body: ClassCrIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ClassCrOut:
    """Mark a student as their class's CR, or clear it with null (endpoint 7)."""
    school_class = db.get(SchoolClass, class_id)
    if school_class is None:
        raise not_found(f"Class {class_id} does not exist.")
    if school_class.class_teacher_id != user.id:
        raise forbidden(f"Only the class teacher of {class_id} can choose its CR.")

    new_cr = None
    if body.student_id is not None:
        new_cr = db.get(User, body.student_id)
        if new_cr is None:
            raise not_found(f"User {body.student_id} does not exist.")
        if new_cr.role != Role.student or not new_cr.is_active:
            raise invalid_input(f"{new_cr.name} is not an active student.")
        if new_cr.class_id != class_id:
            raise invalid_input(f"{new_cr.name} is not in class {class_id}.")

    # Clear the old CR first, so the database never sees two at once.
    for old in db.scalars(select(User).where(User.class_id == class_id, User.is_cr.is_(True))):
        old.is_cr = False
    db.flush()
    if new_cr is not None:
        new_cr.is_cr = True
    db.commit()

    cr = PersonRef(user_id=new_cr.id, name=new_cr.name) if new_cr else None
    return ClassCrOut(class_id=class_id, cr=cr)
