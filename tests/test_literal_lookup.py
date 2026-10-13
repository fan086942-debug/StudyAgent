from sqlalchemy import select

from app.models import Document
from app.schemas.chat import SearchRequest
from tests.test_exams import exam_bytes


def test_short_literal_bypasses_only_location_threshold_and_keeps_scope(exam_app, monkeypatch):
    app, client, course, _ = exam_app
    result = client.post(
        f"/api/courses/{course}/documents",
        files={
            "file": (
                "long_notes.docx",
                exam_bytes("A* 使用 f(n)=g(n)+h(n)。" + "教材中的其他正文内容。" * 100),
            )
        },
        data={"document_type": "notes"},
    )
    document = result.json()["id"]
    app.state.retriever.settings.min_similarity = 0.99
    monkeypatch.setattr(app.state.retriever.vectors, "search", lambda *args: [])
    body = SearchRequest(course_id=course, document_ids=[document], question="A*")
    assert app.state.retriever.search(body).sources == []
    sources = app.state.retriever.locate(body).sources
    assert sources and all(s.document_id == document and "A*" in s.text for s in sources)
    other = client.post(
        f"/api/courses/{course}/documents",
        files={"file": ("other.docx", exam_bytes("BFS 的队列。"))},
        data={"document_type": "notes"},
    ).json()["id"]
    assert (
        app.state.retriever.locate(body.model_copy(update={"document_ids": [other]})).sources == []
    )
    agent = client.post(
        "/api/agent",
        json={"course_id": course, "document_ids": [document], "question": "教材哪里讲了 A*？"},
    ).json()
    assert agent["trace"][0]["tool"] == "locate_source" and agent["sources"]
    with app.state.sessions() as db:
        db.get(Document, document).status = "stale"
        db.commit()
    assert app.state.retriever.locate(body).sources == []


def test_literal_escape_boundaries_and_stale_fingerprint(exam_app, monkeypatch):
    app, client, course, _ = exam_app
    uploaded = client.post(
        f"/api/courses/{course}/documents",
        files={"file": ("literal.docx", exam_bytes("training = AB。A_ 是精确名字。"))},
        data={"document_type": "notes"},
    ).json()["id"]
    monkeypatch.setattr(app.state.retriever.vectors, "search", lambda *args: [])
    body = SearchRequest(course_id=course, document_ids=[uploaded], question="AI")
    assert app.state.retriever.locate(body).sources == []
    assert app.state.retriever.locate(body.model_copy(update={"question": "A_"})).sources
    assert app.state.retriever.locate(body.model_copy(update={"question": "%_"})).sources == []
    with app.state.sessions() as db:
        doc = db.scalar(select(Document).where(Document.id == uploaded))
        doc.embedding_fingerprint = "old-index"
        db.commit()
    assert app.state.retriever.locate(body.model_copy(update={"question": "A_"})).sources == []
