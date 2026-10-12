from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import (
    Conversation,
    Course,
    Document,
    DocumentChunk,
    ExamPaper,
    KnowledgePoint,
    PracticeAttempt,
    Question,
    QuestionKnowledgePoint,
    StudyArtifact,
    StudyPlan,
    WrongQuestion,
)
from tests.test_exams import exam_bytes


def add_history(app, course):
    with app.state.sessions() as session:
        session.add_all(
            [
                Conversation(course_id=course, question="复习", kind="agent", payload={}),
                StudyPlan(
                    course_id=course,
                    title="计划",
                    topics=[],
                    document_ids=[],
                    daily_minutes=30,
                    tasks=[],
                ),
                StudyArtifact(
                    course_id=course,
                    kind="review",
                    title="复习",
                    mode="demo",
                    warning="",
                    payload={},
                ),
                PracticeAttempt(
                    course_id=course, reference_key="snapshot", snapshot={}, outcome="wrong"
                ),
                WrongQuestion(course_id=course, reference_key="snapshot", snapshot={}),
            ]
        )
        session.commit()


def test_course_purges_all_stores_and_keeps_other_course(exam_app):
    app, client, course, doc_id = exam_app
    other = client.post("/api/courses", json={"name": "保留的课程"}).json()["id"]
    other_doc = client.post(
        f"/api/courses/{other}/documents",
        files={"file": ("保留.docx", exam_bytes())},
        data={"document_type": "exam"},
    ).json()["id"]
    add_history(app, course)
    add_history(app, other)
    with app.state.sessions() as session:
        storage = Path(session.get(Document, doc_id).storage_path)
        other_storage = Path(session.get(Document, other_doc).storage_path)
    old = app.state.vectors.client.get_or_create_collection(
        "chunks-old-course", embedding_function=None
    )
    old.upsert(ids=["old"], embeddings=[[1.0, 0.0]], metadatas=[{"document_id": doc_id}])
    response = client.delete(f"/api/courses/{course}")
    assert response.status_code == 200, response.text
    assert response.json() == {"deleted": course}
    assert not storage.exists() and other_storage.exists() and old.count() == 0
    assert client.get(f"/api/courses/{course}/documents").status_code == 404
    assert client.get(f"/api/documents/{doc_id}/file").status_code == 404
    assert client.get(f"/api/documents/{other_doc}/file").status_code == 200
    assert client.delete(f"/api/courses/{course}").status_code == 404
    assert app.state.vectors.collection.count() > 0
    assert app.state.vectors.collection.get(where={"document_id": doc_id})["ids"] == []
    with app.state.sessions() as session:
        assert session.get(Course, course) is None
        assert session.get(Course, other) is not None
        for model in [
            Document,
            DocumentChunk,
            ExamPaper,
            KnowledgePoint,
            Conversation,
            StudyPlan,
            StudyArtifact,
            PracticeAttempt,
            WrongQuestion,
        ]:
            assert list(session.scalars(select(model).where(model.course_id == course))) == []
            assert list(session.scalars(select(model).where(model.course_id == other)))
        other_paper = session.scalar(select(ExamPaper.id).where(ExamPaper.course_id == other))
        assert all(q.paper_id == other_paper for q in session.scalars(select(Question)))
        assert list(session.scalars(select(QuestionKnowledgePoint)))


def test_empty_course_delete_and_missing_course(exam_app):
    _, client, _, _ = exam_app
    empty = client.post("/api/courses", json={"name": "空课程"}).json()["id"]
    assert client.delete(f"/api/courses/{empty}").status_code == 200
    assert client.delete("/api/courses/missing").status_code == 404
    assert all(c["id"] != empty for c in client.get("/api/courses").json())


def test_course_locks_processing_and_all_paths_prevalidated(exam_app, tmp_path):
    app, client, course, doc_id = exam_app
    for lock in [
        app.state.ingestion.lock,
        app.state.exams.lock,
        app.state.generation.lock,
        app.state.learning.lock,
    ]:
        with lock:
            assert client.delete(f"/api/courses/{course}").status_code == 409
        assert not app.state.ingestion.lock.locked()
    with app.state.sessions() as session:
        doc = session.get(Document, doc_id)
        doc.status = "processing"
        session.commit()
    assert client.delete(f"/api/courses/{course}").status_code == 409
    unrelated = tmp_path / "keep.txt"
    unrelated.write_text("keep", encoding="utf-8")
    with app.state.sessions() as session:
        doc = session.get(Document, doc_id)
        doc.status = "ready"
        original = Path(doc.storage_path)
        session.add(
            Document(
                course_id=course,
                name="bad.docx",
                file_type="docx",
                document_type="other",
                sha256="different",
                storage_path=str(unrelated),
                status="ready",
            )
        )
        session.commit()
    assert client.delete(f"/api/courses/{course}").status_code == 500
    assert original.exists() and unrelated.read_text("utf-8") == "keep"
    with app.state.sessions() as session:
        assert session.get(Document, doc_id).status == "ready"


def test_course_partial_failure_can_retry(exam_app, monkeypatch):
    app, client, course, doc_id = exam_app
    extra = client.post(
        f"/api/courses/{course}/documents",
        files={"file": ("额外.docx", exam_bytes("1. 额外题目"))},
        data={"document_type": "exam"},
    ).json()["id"]
    add_history(app, course)
    original = app.state.ingestion._delete_locked
    calls = []

    def fail_second(identifier):
        calls.append(identifier)
        if len(calls) == 2:
            raise OSError("simulated failure")
        return original(identifier)

    monkeypatch.setattr(app.state.ingestion, "_delete_locked", fail_second)
    response = client.delete(f"/api/courses/{course}")
    assert response.status_code == 500 and response.json()["code"] == "course_delete_incomplete"
    with app.state.sessions() as session:
        assert session.get(Course, course)
        assert session.get(Document, calls[0]) is None
        assert session.get(Document, calls[1])
        assert session.scalar(select(Conversation).where(Conversation.course_id == course))
    assert not app.state.connection.exclusive_business and app.state.connection.active_requests == 0
    monkeypatch.setattr(app.state.ingestion, "_delete_locked", original)
    assert client.delete(f"/api/courses/{course}").status_code == 200
    assert client.get(f"/api/documents/{doc_id}/file").status_code == 404
    assert client.get(f"/api/documents/{extra}/file").status_code == 404


def test_existing_request_prevents_course_delete(exam_app):
    app, client, course, doc_id = exam_app
    connection = app.state.connection
    connection.enter_request()
    try:
        assert client.delete(f"/api/courses/{course}").status_code == 409
        assert connection.active_requests == 1 and not connection.exclusive_business
    finally:
        connection.leave_request()
    assert client.get(f"/api/documents/{doc_id}/file").status_code == 200


def test_course_deletion_excludes_new_business_requests(exam_app, monkeypatch):
    app, client, course, _ = exam_app
    started, finish = Event(), Event()
    original = app.state.ingestion._delete_locked

    def blocked(identifier):
        started.set()
        assert finish.wait(10)
        return original(identifier)

    monkeypatch.setattr(app.state.ingestion, "_delete_locked", blocked)
    with ThreadPoolExecutor(max_workers=1) as pool:
        deleting = pool.submit(client.delete, f"/api/courses/{course}")
        try:
            assert started.wait(10)
            response = client.post("/api/courses", json={"name": "cannot race"})
            assert response.status_code == 409 and response.json()["code"] == "course_busy"
            assert response.headers["X-Request-ID"]
            assert app.state.connection.active_requests == 1
            assert client.get("/health").status_code == 200
            local = TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 12345))
            try:
                assert local.put("/api/connection", json={"mode": "demo"}).status_code == 409
            finally:
                local.close()
        finally:
            finish.set()
        assert deleting.result(timeout=10).status_code == 200
    assert app.state.connection.active_requests == 0 and not app.state.connection.exclusive_business
    assert client.post("/api/courses", json={"name": "after cleanup"}).status_code == 201
