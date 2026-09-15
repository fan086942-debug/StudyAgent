import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.db.session import make_database
from app.main import create_app
from app.models import Course, Document


def test_courses_persist(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path)
    with TestClient(create_app(settings)) as client:
        response = client.post("/api/courses", json={"name": "人工智能"})
        assert response.status_code == 201
        course_id = response.json()["id"]
        assert client.post("/api/courses", json={"name": " "}).status_code == 422
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/courses").json()[0]["id"] == course_id


def test_duplicate_constraint_and_foreign_key(tmp_path):
    engine, sessions = make_database(tmp_path)
    with sessions() as session:
        course = Course(name="course")
        session.add(course)
        session.commit()
        values = dict(
            course_id=course.id,
            name="x.pdf",
            file_type="pdf",
            document_type="textbook",
            sha256="abc",
            storage_path="x.pdf",
        )
        session.add(Document(**values))
        session.commit()
        session.add(Document(**values))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        values["course_id"] = "missing"
        session.add(Document(**values))
        with pytest.raises(IntegrityError):
            session.commit()
    engine.dispose()
