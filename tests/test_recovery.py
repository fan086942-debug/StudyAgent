from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.errors import AppError
from app.main import create_app
from app.models import Document
from scripts.make_fixtures import generate
from tests.test_ingestion import upload


def test_restart_recovers_interrupted_and_stale(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path / "db")
    files = generate(tmp_path / "samples")
    app = create_app(settings)
    with TestClient(app) as client:
        course = client.post("/api/courses", json={"name": "AI"}).json()["id"]
        first = upload(client, course, files[0]).json()["id"]
        second = upload(client, course, files[1]).json()["id"]
        with app.state.sessions() as session:
            session.get(Document, first).status = "processing"
            session.get(Document, second).embedding_fingerprint = "old-model"
            session.commit()
    with TestClient(create_app(settings)) as client:
        docs = {d["id"]: d for d in client.get(f"/api/courses/{course}/documents").json()}
        assert docs[first]["status"] == "failed"
        assert docs[second]["status"] == "stale"
        query = {"course_id": course, "question": "A* 算法"}
        assert client.post("/api/search", json=query).json()["sources"] == []
        assert client.post(f"/api/documents/{first}/retry").json()["status"] == "ready"


def test_size_limit_safe_filename_and_busy(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path / "db", max_upload_mb=1)
    app = create_app(settings)
    with TestClient(app) as client:
        course = client.post("/api/courses", json={"name": "AI"}).json()["id"]
        url = f"/api/courses/{course}/documents"
        result = client.post(url, files={"file": ("large.pdf", b"x" * (1024 * 1024 + 1))})
        assert result.status_code == 413
        assert not list((settings.data_dir / "uploads").iterdir())
        app.state.ingestion.lock.acquire()
        try:
            result = client.post(url, files={"file": ("x.pdf", b"x")})
            assert result.status_code == 409
        finally:
            app.state.ingestion.lock.release()
        path = generate(tmp_path / "samples")[0]
        result = client.post(url, files={"file": ("../../outside.pdf", path.read_bytes())})
        assert result.status_code == 201
        assert result.json()["name"] == "outside.pdf"
        with app.state.sessions() as session:
            stored = session.get(Document, result.json()["id"])
            assert str((settings.data_dir / "uploads").resolve()) in stored.storage_path


def test_index_failure_excluded_and_retry(tmp_path, monkeypatch):
    settings = Settings(_env_file=None, data_dir=tmp_path / "db")
    app = create_app(settings)
    with TestClient(app) as client:
        course = client.post("/api/courses", json={"name": "AI"}).json()["id"]
        original = app.state.vectors.add

        def partial_failure(chunks, vectors):
            original(chunks[:1], vectors[:1])
            raise AppError("index_failed", "模拟部分写入失败", 503)

        monkeypatch.setattr(app.state.vectors, "add", partial_failure)
        assert upload(client, course, generate(tmp_path / "samples")[0]).status_code == 503
        assert app.state.vectors.collection.count() == 0
        query = {"course_id": course, "question": "A* 算法"}
        assert client.post("/api/search", json=query).json()["sources"] == []
        doc = client.get(f"/api/courses/{course}/documents").json()[0]
        monkeypatch.setattr(app.state.vectors, "add", original)
        assert client.post(f"/api/documents/{doc['id']}/retry").status_code == 200
