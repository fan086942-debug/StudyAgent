import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import Settings
from app.core.errors import AppError
from app.main import create_app
from app.models import DocumentChunk
from scripts.make_fixtures import generate


@pytest.fixture
def client_and_files(tmp_path):
    files = generate(tmp_path / "fixtures")
    app = create_app(Settings(_env_file=None, data_dir=tmp_path / "db"))
    with TestClient(app) as client:
        course = client.post("/api/courses", json={"name": "人工智能"}).json()
        yield client, app, course["id"], files


def upload(client, course_id, path):
    with path.open("rb") as stream:
        return client.post(
            f"/api/courses/{course_id}/documents",
            files={"file": (path.name, stream)},
            data={"document_type": "textbook"},
        )


def test_upload_three_and_duplicate(client_and_files):
    client, app, course_id, files = client_and_files
    for path in files:
        response = upload(client, course_id, path)
        assert response.status_code == 201, response.text
        assert response.json()["status"] == "ready"
        assert response.json()["chunk_count"] > 0
    assert upload(client, course_id, files[0]).status_code == 409
    docs = client.get(f"/api/courses/{course_id}/documents").json()
    assert len(docs) == 3
    assert client.get(f"/api/documents/{docs[0]['id']}/file").status_code == 200
    before = app.state.vectors.collection.count()
    assert client.post(f"/api/documents/{docs[0]['id']}/retry").status_code == 200
    assert app.state.vectors.collection.count() == before
    with app.state.sessions() as session:
        assert len(list(session.scalars(select(DocumentChunk)))) == before


def test_failed_embedding_retry(client_and_files, monkeypatch):
    client, app, course_id, files = client_and_files
    original = app.state.embeddings.embed

    def fail(texts):
        raise AppError("embedding_failed", "Embedding 测试故障", 502)

    monkeypatch.setattr(app.state.embeddings, "embed", fail)
    assert upload(client, course_id, files[0]).status_code == 502
    doc = client.get(f"/api/courses/{course_id}/documents").json()[0]
    assert doc["status"] == "failed"
    assert app.state.vectors.collection.count() == 0
    monkeypatch.setattr(app.state.embeddings, "embed", original)
    assert client.post(f"/api/documents/{doc['id']}/retry").json()["status"] == "ready"


def test_invalid_uploads(client_and_files):
    client, _, course_id, _ = client_and_files
    url = f"/api/courses/{course_id}/documents"
    assert client.post(url, files={"file": ("a.ppt", b"bad")}).status_code == 415
    assert client.post(url, files={"file": ("a.pdf", b"")}).status_code == 400
    assert client.post(url, files={"file": ("a.pdf", b"bad")}).status_code == 400
    assert client.post("/api/documents/missing/retry").status_code == 404
