from pathlib import Path

import pytest
from fastapi import BackgroundTasks, Response
from fastapi.testclient import TestClient
from pypdf import PdfReader, PdfWriter
from sqlalchemy import select

from app.api.documents import process_uploaded, queue_document
from app.core.config import Settings
from app.core.errors import AppError
from app.main import create_app
from app.models import DocumentChunk
from app.rag.parsers import ocr, parse_document
from scripts.make_ocr_fixture import make_scan


def test_real_chinese_english_mixed_pdf_and_cache(tmp_path, monkeypatch):
    path = make_scan(tmp_path / "mixed.pdf", mixed=True)
    cache = tmp_path / "cache"
    progress = []
    parsed = parse_document(path, cache_dir=cache, progress=lambda *args: progress.append(args))
    assert [block.page for block in parsed.blocks] == [1, 2]
    assert "Native text" in parsed.blocks[0].text
    assert "Machine Learning" in parsed.blocks[1].text
    assert "labeled data" in parsed.blocks[1].text
    if Path("C:/Windows/Fonts/msyh.ttc").exists():
        assert "机器学习" in parsed.blocks[1].text
    assert parsed.blocks[1].location_type == "pdf_page" and parsed.blocks[1].block_index == 2
    assert any("1 页执行本地 OCR" in warning for warning in parsed.warnings)
    assert any("1 页未提取" in warning for warning in parsed.warnings)
    assert (2, 3, "ocr") in progress
    assert (cache / "page-2.json").exists()

    def fail():
        raise AssertionError("OCR inference must not run for cached pages")

    monkeypatch.setattr(ocr, "get_engine", fail)
    assert parse_document(path, cache_dir=cache).blocks == parsed.blocks


def test_ocr_disabled_encrypted_and_empty(tmp_path):
    path = make_scan(tmp_path / "scan.pdf")
    with pytest.raises(AppError) as error:
        parse_document(path, settings=Settings(_env_file=None, ocr_enabled=False))
    assert error.value.code == "no_text"
    writer = PdfWriter()
    writer.append(PdfReader(path))
    writer.encrypt("private")
    encrypted = tmp_path / "encrypted.pdf"
    writer.write(encrypted)
    with pytest.raises(AppError) as error:
        parse_document(encrypted)
    assert error.value.code == "encrypted_pdf"


def test_background_ocr_indexes_search_and_deletes_cache(tmp_path):
    path = make_scan(tmp_path / "scan.pdf")
    app = create_app(Settings(_env_file=None, data_dir=tmp_path / "db", min_similarity=0))
    with TestClient(app) as client:
        course = client.post("/api/courses", json={"name": "isolated OCR"}).json()["id"]
        response = client.post(
            f"/api/courses/{course}/documents",
            files={"file": (path.name, path.read_bytes())},
            data={"document_type": "textbook", "background": "true"},
        )
        assert response.status_code == 202, response.text
        assert response.json()["status"] == "processing"
        document_id = response.json()["id"]
        doc = client.get(f"/api/courses/{course}/documents").json()[0]
        assert doc["status"] == "ready" and doc["chunk_count"] > 0
        assert "OCR" in doc["warning"]
        assert app.state.connection.active_requests == 0
        cache = app.state.settings.data_dir / "ocr" / document_id
        assert (cache / "page-1.json").exists()
        result = client.post(
            "/api/search",
            json={
                "course_id": course,
                "document_ids": [document_id],
                "question": "Machine Learning",
            },
        ).json()
        assert result["sources"] and result["sources"][0]["page"] == 1
        assert "Learning" in result["sources"][0]["text"]
        assert client.delete(f"/api/documents/{document_id}").status_code == 200
        assert not cache.exists()
        with app.state.sessions() as session:
            assert list(session.scalars(select(DocumentChunk))) == []


def test_ocr_failure_retries_cached_pages(exam_app, tmp_path, monkeypatch):
    app, client, course, _ = exam_app
    path = make_scan(tmp_path / "scan.pdf")
    original = app.state.embeddings.embed

    def fail(texts):
        raise AppError("embedding_failed", "index test failure", 502)

    monkeypatch.setattr(app.state.embeddings, "embed", fail)
    response = client.post(
        f"/api/courses/{course}/documents",
        files={"file": (path.name, path.read_bytes())},
        data={"background": "true"},
    )
    assert response.status_code == 202
    identifier = response.json()["id"]
    docs = {doc["id"]: doc for doc in client.get(f"/api/courses/{course}/documents").json()}
    assert docs[identifier]["status"] == "failed"
    assert docs[identifier]["warning"] is None
    assert app.state.connection.active_requests == 0
    monkeypatch.setattr(app.state.embeddings, "embed", original)
    monkeypatch.setattr(ocr, "get_engine", lambda: pytest.fail("retry should reuse OCR cache"))
    assert client.post(f"/api/documents/{identifier}/retry?background=true").status_code == 202
    docs = {doc["id"]: doc for doc in client.get(f"/api/courses/{course}/documents").json()}
    assert docs[identifier]["status"] == "ready"


def test_queued_job_keeps_request_guard_and_busy_retry(exam_app):
    app, client, course, identifier = exam_app
    from types import SimpleNamespace

    request, tasks, response = SimpleNamespace(app=app), BackgroundTasks(), Response()
    queued = queue_document(request, identifier, tasks, response)
    assert queued.status == "processing" and response.status_code == 202
    assert app.state.connection.active_requests == 1
    try:
        assert client.delete(f"/api/courses/{course}").status_code == 409
        assert client.post(f"/api/documents/{identifier}/retry?background=true").status_code == 409
    finally:
        process_uploaded(app.state, identifier)
    assert app.state.connection.active_requests == 0


def test_cache_corruption_recomputes_and_delete_checks_paths(tmp_path, monkeypatch):
    path = make_scan(tmp_path / "scan.pdf")
    cache = tmp_path / "ocr" / "document"
    first = parse_document(path, cache_dir=cache)
    (cache / "page-1.json").write_text("incomplete", "utf-8")
    assert parse_document(path, cache_dir=cache).blocks == first.blocks
    outside = tmp_path / "outside.txt"
    outside.write_text("keep", "utf-8")
    with pytest.raises(AppError):
        ocr.delete_ocr_cache(tmp_path, "../outside.txt")
    assert outside.read_text("utf-8") == "keep"
    ocr.delete_ocr_cache(tmp_path, "document")
    assert not cache.exists()
