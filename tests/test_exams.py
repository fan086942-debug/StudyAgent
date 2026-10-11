from io import BytesIO

import pytest
from docx import Document as WordDocument
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import Settings
from app.core.errors import AppError
from app.main import create_app
from app.models import KnowledgePoint, Question, QuestionKnowledgePoint


def exam_bytes(text=None):
    doc = WordDocument()
    for line in (
        text
        or "一、选择题\n1. A* 的评价函数？（2分）【知识点：A*】\nA. g+h\nB. g-h\n二、简答题\n1. 解释启发式。【知识点：A*、启发式函数】"
    ).splitlines():
        doc.add_paragraph(line)
    stream = BytesIO()
    doc.save(stream)
    return stream.getvalue()


@pytest.fixture
def exam_app(tmp_path):
    app = create_app(Settings(_env_file=None, data_dir=tmp_path, min_similarity=0.0))
    with TestClient(app) as client:
        course = client.post("/api/courses", json={"name": "AI"}).json()["id"]
        doc = client.post(
            f"/api/courses/{course}/documents",
            files={"file": ("2025期末.docx", exam_bytes())},
            data={"document_type": "exam"},
        )
        assert doc.status_code == 201, doc.text
        yield app, client, course, doc.json()["id"]


def test_exam_upload_scope_retry_and_persistence(exam_app):
    app, client, course, doc_id = exam_app
    paper = client.get(f"/api/courses/{course}/papers").json()[0]
    assert paper["status"] == "ready" and paper["question_count"] == 2
    questions = client.post(f"/api/courses/{course}/questions/search", json={"number": "1"}).json()
    assert len(questions) == 2 and questions[0]["id"] != questions[1]["id"]
    assert questions[0]["locations"][0]["location_type"] == "paragraph"
    assert len(client.get(f"/api/courses/{course}/knowledge-points").json()) == 2
    other = client.post("/api/courses", json={"name": "other"}).json()["id"]
    assert client.get(f"/api/courses/{other}/questions/{questions[0]['id']}").status_code == 404
    assert client.post(f"/api/documents/{doc_id}/extract-questions").status_code == 200
    with app.state.sessions() as session:
        assert len(list(session.scalars(select(Question)))) == 2
        assert len(list(session.scalars(select(KnowledgePoint)))) == 2
        assert len(list(session.scalars(select(QuestionKnowledgePoint)))) == 3
    assert (
        client.post(f"/api/courses/{course}/questions/search", json={"query": "不存在词"}).json()
        == []
    )


def test_failed_extraction_hides_old_questions_and_recovers(exam_app, monkeypatch):
    app, client, course, doc_id = exam_app
    import app.services.exams as module

    original = module.rule_extract

    def fail(_):
        raise AppError("test_failure", "测试解析故障")

    monkeypatch.setattr(module, "rule_extract", fail)
    assert client.post(f"/api/documents/{doc_id}/extract-questions").status_code == 400
    assert client.get(f"/api/courses/{course}/papers").json()[0]["status"] == "failed"
    assert client.post(f"/api/courses/{course}/questions/search", json={}).json() == []
    # 解析失败不破坏 Phase 1 的文档与向量。
    assert client.get(f"/api/courses/{course}/documents").json()[0]["status"] == "ready"
    monkeypatch.setattr(module, "rule_extract", original)
    assert client.post(f"/api/documents/{doc_id}/extract-questions").status_code == 200
