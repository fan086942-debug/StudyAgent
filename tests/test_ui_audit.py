import hashlib
from io import BytesIO
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from reportlab.pdfgen.canvas import Canvas

from app.core.config import Settings
from app.main import create_app
from app.models import Conversation, Course, Document, StudyArtifact
from tests.test_auth import register, settings


def add_pdf(state):
    stream = BytesIO()
    canvas = Canvas(stream)
    canvas.drawString(60, 750, "StudyAgent reference: A* uses f(n) = g(n) + h(n).")
    canvas.showPage()
    canvas.save()
    data = stream.getvalue()
    identifier = uuid4().hex
    path = state.settings.data_dir / "uploads" / f"{identifier}.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    with state.sessions() as session:
        course = Course(name="Preview")
        session.add(course)
        session.flush()
        doc = Document(
            id=identifier, course_id=course.id, name="preview.pdf",
            file_type="pdf", document_type="textbook",
            sha256=hashlib.sha256(data).hexdigest(), storage_path=str(path), status="ready",
        )
        session.add(doc)
        session.commit()
        return doc.id


@pytest.fixture
def preview_app(tmp_path):
    app = create_app(Settings(_env_file=None, data_dir=tmp_path))
    with TestClient(app) as client:
        identifier = add_pdf(app.state)
        yield app, client, identifier


def test_pdf_preview_cache_dimensions_etag_and_invalidation(preview_app, monkeypatch):
    app, client, identifier = preview_app
    url = f"/api/documents/{identifier}/pages/1?width=600"
    result = client.get(url)
    assert result.status_code == 200
    assert result.headers["content-type"] == "image/jpeg"
    with Image.open(BytesIO(result.content)) as image:
        assert image.width <= 600 and image.height <= 2400
    assert len(list((app.state.settings.data_dir / "preview-cache").glob("*.jpg"))) == 1
    import app.api.documents as module

    def fail(*args, **kwargs):
        raise AssertionError("cache hit must not render again")

    monkeypatch.setattr(module, "render_pdf_page", fail)
    assert client.get(url).content == result.content
    assert client.get(url, headers={"If-None-Match": result.headers["etag"]}).status_code == 304
    with app.state.sessions() as session:
        session.get(Document, identifier).status = "deleting"
        session.commit()
    assert client.get(url, headers={"If-None-Match": result.headers["etag"]}).status_code == 409


@pytest.mark.parametrize("suffix,code", [
    ("0", 404), ("2", 404), ("-1", 404), ("1?width=1", 422), ("1?width=99999", 422),
])
def test_preview_rejects_invalid_pages_and_widths(preview_app, suffix, code):
    _, client, identifier = preview_app
    assert client.get(f"/api/documents/{identifier}/pages/{suffix}").status_code == code


def test_preview_rejects_non_pdf_and_outside_paths(preview_app, tmp_path):
    app, client, identifier = preview_app
    with app.state.sessions() as session:
        doc = session.get(Document, identifier)
        doc.file_type = "docx"
        session.commit()
    assert client.get(f"/api/documents/{identifier}/pages/1").status_code == 415
    with app.state.sessions() as session:
        doc = session.get(Document, identifier)
        doc.file_type = "pdf"
        doc.storage_path = str(tmp_path / "outside.pdf")
        session.commit()
    assert client.get(f"/api/documents/{identifier}/pages/1").status_code == 500


def test_deleting_document_removes_its_previews(preview_app):
    app, client, identifier = preview_app
    assert client.get(f"/api/documents/{identifier}/pages/1").status_code == 200
    assert list((app.state.settings.data_dir / "preview-cache").glob("*.jpg"))
    assert client.delete(f"/api/documents/{identifier}").status_code == 200
    assert not list((app.state.settings.data_dir / "preview-cache").glob("*.jpg"))
    assert client.get(f"/api/documents/{identifier}/pages/1").status_code == 404


def test_history_and_artifact_summaries_include_saved_evidence_counts(preview_app):
    app, client, identifier = preview_app
    with app.state.sessions() as session:
        course = session.get(Document, identifier).course_id
        session.add(Conversation(
            course_id=course, kind="chat", question="A* 的评价函数？", document_ids=None,
            payload={"answer": "已知代价加估计代价。" * 30, "sources": [{}, {}],
                     "answer_basis": "materials"},
        ))
        session.add(StudyArtifact(
            course_id=course, kind="study_pack", title="搜索复习", mode="demo", warning="",
            payload={"content": {"sections": [{"topic": "A*"}, {"topic": "BFS"}],
                                 "questions": [{"topic": "A*"}]}, "sources": [{}, {}]},
        ))
        session.commit()
    history = client.get(f"/api/courses/{course}/conversations").json()[0]
    assert history["source_count"] == 2 and history["answer_basis"] == "materials"
    assert len(history["answer_excerpt"]) == 180
    artifact = client.get(f"/api/courses/{course}/artifacts").json()[0]
    assert artifact["section_count"] == 2 and artifact["question_count"] == 1
    assert artifact["topic_count"] == 2 and artifact["source_count"] == 2


def test_preview_requires_login_and_uses_account_workspace(tmp_path):
    app = create_app(settings(tmp_path))
    with TestClient(app) as client:
        assert client.get("/api/documents/private/pages/1").status_code == 401
        register(client, "preview_owner")
        with app.state.auth.sessions() as session:
            from app.services.auth import User
            owner = session.query(User).filter_by(username="preview_owner").one()
        state = app.state.workspaces.get(owner)
        identifier = add_pdf(state)
        assert client.get(f"/api/documents/{identifier}/pages/1").status_code == 200
        client.post("/api/auth/logout")
        register(client, "preview_other")
        assert client.get(f"/api/documents/{identifier}/pages/1").status_code == 404
