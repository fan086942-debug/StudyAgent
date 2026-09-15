from fastapi import APIRouter, Request
from sqlalchemy import select

from app.models import Course
from app.schemas.document import CourseCreate, CourseOut

router = APIRouter(prefix="/api/courses", tags=["courses"])


@router.post("", response_model=CourseOut, status_code=201)
def create_course(body: CourseCreate, request: Request):
    with request.app.state.sessions() as session:
        course = Course(name=body.name.strip(), description=body.description)
        session.add(course)
        session.commit()
        return course


@router.get("", response_model=list[CourseOut])
def list_courses(request: Request):
    with request.app.state.sessions() as session:
        return list(session.scalars(select(Course).order_by(Course.created_at.desc())))
