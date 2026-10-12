from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from types import SimpleNamespace

from fastapi import BackgroundTasks, Response
from sqlalchemy import select

from app.api.documents import process_uploaded, queue_document
from app.models import Document, DocumentChunk
from app.rag.parsers.ocr import PageOCR
from scripts.make_ocr_fixture import make_scan
from tests.test_exams import exam_bytes


def test_cancel_queued_job_before_it_starts(exam_app):
    app, client, course, identifier = exam_app
    response = Response()
    queue_document(SimpleNamespace(app=app), identifier, BackgroundTasks(), response)
    assert response.status_code == 202
    try:
        result = client.post(f"/api/documents/{identifier}/cancel")
        assert result.status_code == 202 and result.json()["status"] == "cancelling"
        assert client.post(f"/api/documents/{identifier}/retry").status_code == 409
        assert client.post(f"/api/documents/{identifier}/retry?background=true").status_code == 409
        assert client.delete(f"/api/documents/{identifier}").status_code == 409
        assert client.delete(f"/api/courses/{course}").status_code == 409
    finally:
        process_uploaded(app.state, identifier)
    with app.state.sessions() as session:
        document = session.get(Document, identifier)
        assert document.status == "cancelled" and document.chunk_count == 0
        assert Path(document.storage_path).exists()
        assert (
            list(
                session.scalars(
                    select(DocumentChunk).where(DocumentChunk.document_id == identifier)
                )
            )
            == []
        )
    assert app.state.connection.active_requests == 0
    assert client.post(f"/api/documents/{identifier}/cancel").json()["status"] == "cancelled"
    assert client.post(f"/api/documents/{identifier}/retry?background=true").status_code == 202
    assert client.get(f"/api/courses/{course}/documents").json()[0]["status"] == "ready"


def test_cancel_during_page_preserves_cache_then_resume(exam_app, tmp_path, monkeypatch):
    app, client, course, _ = exam_app
    scan = make_scan(tmp_path / "cancel.pdf", copies=3)
    page_done, release = Event(), Event()
    original = PageOCR.read

    def hold_after_page(self, page, number):
        text = original(self, page, number)
        if number == 1:
            page_done.set()
            assert release.wait(15)
        return text

    monkeypatch.setattr(PageOCR, "read", hold_after_page)
    with ThreadPoolExecutor(max_workers=1) as pool:
        uploading = pool.submit(
            client.post,
            f"/api/courses/{course}/documents",
            files={"file": (scan.name, scan.read_bytes())},
            data={"background": "true"},
        )
        try:
            assert page_done.wait(15)
            document = next(
                doc
                for doc in client.get(f"/api/courses/{course}/documents").json()
                if doc["name"] == scan.name
            )
            identifier = document["id"]
            cache = app.state.settings.data_dir / "ocr" / identifier
            assert (cache / "page-1.json").exists()
            original_cache_time = (cache / "page-1.json").stat().st_mtime_ns
            for _ in range(2):
                result = client.post(f"/api/documents/{identifier}/cancel")
                assert result.status_code == 202 and result.json()["status"] == "cancelling"
            assert (
                client.post(f"/api/documents/{identifier}/retry?background=true").status_code == 409
            )
            assert client.delete(f"/api/documents/{identifier}").status_code == 409
            assert (
                client.post(
                    "/api/search",
                    json={
                        "course_id": course,
                        "document_ids": [identifier],
                        "question": "Machine Learning",
                    },
                ).json()["sources"]
                == []
            )
        finally:
            release.set()
        assert uploading.result(timeout=15).status_code == 202
    docs = {doc["id"]: doc for doc in client.get(f"/api/courses/{course}/documents").json()}
    assert docs[identifier]["status"] == "cancelled" and docs[identifier]["chunk_count"] == 0
    assert "处理已取消" in docs[identifier]["error"] and docs[identifier]["warning"] is None
    assert not (cache / "page-2.json").exists()
    assert app.state.connection.active_requests == 0
    assert app.state.vectors.collection.get(where={"document_id": identifier})["ids"] == []
    monkeypatch.setattr(PageOCR, "read", original)
    assert client.post(f"/api/documents/{identifier}/retry?background=true").status_code == 202
    assert (cache / "page-1.json").stat().st_mtime_ns == original_cache_time
    assert (cache / "page-3.json").exists()
    docs = {doc["id"]: doc for doc in client.get(f"/api/courses/{course}/documents").json()}
    assert docs[identifier]["status"] == "ready"


def test_cancel_during_embedding_stops_next_batch(exam_app, monkeypatch):
    app, client, course, _ = exam_app
    original = app.state.embeddings.embed
    calls = []

    def cancel_after_batch(texts):
        with app.state.sessions() as session:
            identifier = session.scalar(
                select(Document.id).where(Document.name == "embedding.docx")
            )
        calls.append(len(texts))
        app.state.ingestion.cancel(identifier)
        return original(texts)

    monkeypatch.setattr(app.state.embeddings, "embed", cancel_after_batch)
    result = client.post(
        f"/api/courses/{course}/documents",
        files={"file": ("embedding.docx", exam_bytes("large text " * 2400))},
    )
    assert result.status_code == 409 and result.json()["code"] == "processing_cancelled"
    assert calls == [16]
    with app.state.sessions() as session:
        doc = session.scalar(select(Document).where(Document.name == "embedding.docx"))
        assert doc.status == "cancelled" and Path(doc.storage_path).exists()
        assert app.state.vectors.collection.get(where={"document_id": doc.id})["ids"] == []


def test_cancel_after_partial_vector_write_cleans_index(exam_app, monkeypatch):
    app, client, course, _ = exam_app
    original = app.state.vectors.add

    def cancel_after_write(chunks, embeddings):
        original(chunks, embeddings)
        app.state.ingestion.cancel(chunks[0].document_id)

    monkeypatch.setattr(app.state.vectors, "add", cancel_after_write)
    result = client.post(
        f"/api/courses/{course}/documents",
        files={"file": ("vectors.docx", exam_bytes("1. vector cancel"))},
    )
    assert result.status_code == 409
    with app.state.sessions() as session:
        doc = session.scalar(select(Document).where(Document.name == "vectors.docx"))
        assert doc.status == "cancelled"
        assert (
            list(session.scalars(select(DocumentChunk).where(DocumentChunk.document_id == doc.id)))
            == []
        )
        assert app.state.vectors.collection.get(where={"document_id": doc.id})["ids"] == []


def test_cancel_missing_finished_failed_documents_do_not_change(exam_app):
    app, client, _, identifier = exam_app
    assert client.post("/api/documents/missing/cancel").status_code == 404
    assert client.post(f"/api/documents/{identifier}/cancel").status_code == 409
    with app.state.sessions() as session:
        doc = session.get(Document, identifier)
        assert doc.status == "ready"
        doc.status, doc.error = "failed", "keep this error"
        session.commit()
    assert client.post(f"/api/documents/{identifier}/cancel").status_code == 409
    with app.state.sessions() as session:
        assert session.get(Document, identifier).error == "keep this error"
