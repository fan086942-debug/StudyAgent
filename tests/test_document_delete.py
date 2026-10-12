from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import Settings
from app.core.errors import AppError
from app.main import create_app
from app.models import Document, DocumentChunk, QuestionKnowledgePoint
from tests.test_exams import exam_bytes


def test_clean_start_and_empty_new_course(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path)
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/courses").json() == []
        course = client.post("/api/courses", json={"name": "我的第一门课"}).json()["id"]
        assert client.get(f"/api/courses/{course}/documents").json() == []
        assert client.get(f"/api/courses/{course}/progress").json()["ready_documents"] == 0
    with TestClient(create_app(settings)) as restarted:
        assert len(restarted.get("/api/courses").json()) == 1
        assert restarted.get(f"/api/courses/{course}/documents").json() == []


def test_delete_exam_file_chunks_vectors_and_keep_snapshots(exam_app):
    app, client, course, doc_id = exam_app
    question = client.post(f"/api/courses/{course}/questions/search", json={}).json()[0]
    assert (
        client.post(
            f"/api/courses/{course}/practice",
            json={"reference_type": "question", "reference_id": question["id"], "outcome": "wrong"},
        ).status_code
        == 201
    )
    with app.state.sessions() as session:
        storage = Path(session.get(Document, doc_id).storage_path)
    # An old embedding collection must be cleaned as well.
    old = app.state.vectors.client.get_or_create_collection(
        "chunks-old-embedding", embedding_function=None
    )
    old.upsert(ids=["old-vector"], embeddings=[[1.0, 0.0]], metadatas=[{"document_id": doc_id}])
    response = client.delete(f"/api/documents/{doc_id}")
    assert response.status_code == 200, response.text
    assert not storage.exists()
    assert app.state.vectors.collection.count() == 0 and old.count() == 0
    assert client.get(f"/api/courses/{course}/documents").json() == []
    assert client.get(f"/api/courses/{course}/papers").json() == []
    assert client.post(f"/api/courses/{course}/questions/search", json={}).json() == []
    assert client.get(f"/api/courses/{course}/knowledge-points").json() == []
    assert client.get(f"/api/documents/{doc_id}/file").status_code == 404
    assert client.delete(f"/api/documents/{doc_id}").status_code == 404
    wrongs = client.get(f"/api/courses/{course}/wrongbook").json()
    assert len(wrongs) == 1
    progress = client.get(f"/api/courses/{course}/progress").json()
    assert progress["ready_documents"] == 0 and progress["attempts"] == 1
    with app.state.sessions() as session:
        assert session.get(Document, doc_id) is None
        assert list(session.scalars(select(DocumentChunk))) == []
        assert list(session.scalars(select(QuestionKnowledgePoint))) == []
    # Same file can be uploaded again after deleting the old content hash.
    assert (
        client.post(
            f"/api/courses/{course}/documents",
            files={"file": ("重新上传.docx", exam_bytes())},
            data={"document_type": "exam"},
        ).status_code
        == 201
    )


def test_delete_failure_stops_search_and_can_retry(exam_app, monkeypatch):
    app, client, course, doc_id = exam_app
    original = app.state.vectors.delete_document_everywhere

    def fail(identifier):
        raise AppError("index_failed", "模拟向量清理失败", 503)

    monkeypatch.setattr(app.state.vectors, "delete_document_everywhere", fail)
    assert client.delete(f"/api/documents/{doc_id}").status_code == 503
    docs = client.get(f"/api/courses/{course}/documents").json()
    assert docs[0]["status"] == "deleting"
    assert client.get(f"/api/documents/{doc_id}/file").status_code == 409
    assert client.post(f"/api/documents/{doc_id}/retry").status_code == 409
    assert client.get(f"/api/courses/{course}/progress").json()["ready_documents"] == 0
    assert (
        client.post("/api/search", json={"course_id": course, "question": "A*"}).json()["sources"]
        == []
    )
    monkeypatch.setattr(app.state.vectors, "delete_document_everywhere", original)
    assert client.delete(f"/api/documents/{doc_id}").status_code == 200


def test_busy_and_path_guards(exam_app, tmp_path):
    app, client, _, doc_id = exam_app
    for lock in [app.state.ingestion.lock, app.state.exams.lock]:
        with lock:
            assert client.delete(f"/api/documents/{doc_id}").status_code == 409
    assert not app.state.ingestion.lock.locked()
    unrelated = tmp_path / "do-not-delete.txt"
    unrelated.write_text("keep", encoding="utf-8")
    with app.state.sessions() as session:
        doc = session.get(Document, doc_id)
        doc.storage_path = str(unrelated)
        session.commit()
    assert client.delete(f"/api/documents/{doc_id}").status_code == 500
    assert unrelated.read_text("utf-8") == "keep"
    with app.state.sessions() as session:
        assert session.get(Document, doc_id).status == "ready"


def test_other_documents_and_courses_are_untouched(exam_app):
    _, client, course, doc_id = exam_app
    other = client.post("/api/courses", json={"name": "另一门课"}).json()["id"]
    other_doc = client.post(
        f"/api/courses/{other}/documents",
        files={"file": ("另一份.docx", exam_bytes())},
        data={"document_type": "exam"},
    ).json()["id"]
    assert client.delete(f"/api/documents/{doc_id}").status_code == 200
    assert client.get(f"/api/courses/{course}/documents").json() == []
    assert len(client.get(f"/api/courses/{other}/papers").json()) == 1
    assert client.get(f"/api/documents/{other_doc}/file").status_code == 200


def test_file_cleanup_failure_can_retry(exam_app, monkeypatch):
    app, client, course, doc_id = exam_app
    original = Path.unlink

    def fail(path, *args, **kwargs):
        if path.name == doc_id + ".docx":
            raise PermissionError("file locked")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail)
    assert client.delete(f"/api/documents/{doc_id}").status_code == 500
    assert client.get(f"/api/courses/{course}/documents").json()[0]["status"] == "deleting"
    monkeypatch.setattr(Path, "unlink", original)
    assert client.delete(f"/api/documents/{doc_id}").status_code == 200
