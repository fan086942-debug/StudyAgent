from io import BytesIO
from types import SimpleNamespace
from zipfile import ZIP_STORED, ZipFile

import pytest
from fastapi import UploadFile

from app.api.documents import upload_document
from app.core.config import Settings
from app.core.errors import AppError
from tests.test_exams import exam_bytes


def test_default_limit_and_real_docx_over_old_limit(exam_app):
    _, client, course, _ = exam_app
    assert Settings(_env_file=None).max_upload_mb == 200
    assert client.get("/health").json()["max_upload_mb"] == 200
    stream = BytesIO(exam_bytes("1. 大文件验收"))
    with ZipFile(stream, "a") as archive:
        archive.writestr(
            "large-upload-fixture.bin", b"x" * (26 * 1024 * 1024), compress_type=ZIP_STORED
        )
    response = client.post(
        f"/api/courses/{course}/documents",
        files={"file": ("26MB.docx", stream.getvalue())},
        data={"document_type": "exam"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "ready"


def test_exact_200mb_boundary_and_oversize_cleanup(exam_app, monkeypatch):
    app, _, course, _ = exam_app

    class Stream:
        def __init__(self, size):
            self.remaining = size

        def read(self, size):
            length = min(self.remaining, size)
            self.remaining -= length
            return b"x" * length

    # Test upload storage's size boundary without running a parser on synthetic bytes.
    monkeypatch.setattr(app.state.ingestion, "process", lambda identifier: {"id": identifier})
    request = SimpleNamespace(app=app, state=SimpleNamespace(services=app.state))
    root = app.state.settings.data_dir / "uploads"
    limit = 200 * 1024 * 1024
    uploaded = upload_document(
        course, request, UploadFile(Stream(limit), filename="boundary.pdf"), "other"
    )
    assert (root / (uploaded["id"] + ".pdf")).stat().st_size == limit
    before = set(root.iterdir())
    with pytest.raises(AppError) as error:
        upload_document(
            course, request, UploadFile(Stream(limit + 1), filename="oversize.pdf"), "other"
        )
    assert error.value.status == 413 and error.value.code == "upload_too_large"
    assert set(root.iterdir()) == before
