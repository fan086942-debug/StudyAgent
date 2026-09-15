import hashlib
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.errors import AppError
from app.models import Course, Document
from app.schemas.document import DocumentOut, DocumentType

router = APIRouter(prefix="/api", tags=["documents"])


@router.get("/courses/{course_id}/documents", response_model=list[DocumentOut])
def list_documents(course_id: str, request: Request):
    with request.app.state.sessions() as session:
        if session.get(Course, course_id) is None:
            raise AppError("course_not_found", "课程不存在", 404)
        return list(
            session.scalars(
                select(Document)
                .where(Document.course_id == course_id)
                .order_by(Document.created_at.desc())
            )
        )


@router.post("/courses/{course_id}/documents", response_model=DocumentOut, status_code=201)
def upload_document(
    course_id: str,
    request: Request,
    file: UploadFile = File(...),
    document_type: DocumentType = Form("other"),
):
    settings = request.app.state.settings
    name = (file.filename or "upload").replace("\\", "/").split("/")[-1][:255]
    suffix = Path(name).suffix.lower()
    if suffix not in {".pdf", ".pptx", ".docx"}:
        raise AppError("unsupported_type", "仅支持 PDF、PPTX、DOCX；PPT/DOC 请先转换", 415)
    with request.app.state.sessions() as session:
        if session.get(Course, course_id) is None:
            raise AppError("course_not_found", "课程不存在", 404)
        if request.app.state.ingestion.lock.locked():
            raise AppError("ingestion_busy", "已有资料正在处理，请稍后上传", 409)
        identifier = uuid4().hex
        directory = settings.data_dir / "uploads"
        directory.mkdir(parents=True, exist_ok=True)
        path = (directory / (identifier + suffix)).resolve()
        digest, size = hashlib.sha256(), 0
        try:
            with path.open("wb") as target:
                while block := file.file.read(1024 * 1024):
                    size += len(block)
                    if size > settings.max_upload_mb * 1024 * 1024:
                        raise AppError("upload_too_large", "文件超过上传大小限制", 413)
                    digest.update(block)
                    target.write(block)
            if size == 0:
                raise AppError("empty_file", "不能上传空文件")
            document = Document(
                id=identifier,
                course_id=course_id,
                name=name,
                file_type=suffix[1:],
                document_type=document_type,
                sha256=digest.hexdigest(),
                storage_path=str(path),
            )
            session.add(document)
            session.commit()
        except Exception as exc:
            session.rollback()
            path.unlink(missing_ok=True)
            if isinstance(exc, IntegrityError):
                raise AppError(
                    "duplicate_document", "本课程已上传相同内容，请使用已有资料或重试", 409
                ) from exc
            raise
    try:
        return request.app.state.ingestion.process(identifier)
    except AppError as exc:
        # 与另一个上传恰好竞争时，已保存的文件应能重试，而非永远 processing。
        if exc.code == "ingestion_busy":
            with request.app.state.sessions() as session:
                doc = session.get(Document, identifier)
                doc.status, doc.error = "failed", exc.message
                session.commit()
        raise


@router.post("/documents/{document_id}/retry", response_model=DocumentOut)
def retry(document_id: str, request: Request):
    return request.app.state.ingestion.process(document_id)


@router.get("/documents/{document_id}/file")
def download(document_id: str, request: Request):
    with request.app.state.sessions() as session:
        doc = session.get(Document, document_id)
        if doc is None:
            raise AppError("document_not_found", "资料不存在", 404)
        path = Path(doc.storage_path).resolve()
        if not path.is_relative_to((request.app.state.settings.data_dir / "uploads").resolve()):
            raise AppError("invalid_file_path", "资料存储路径异常", 500)
        if not path.exists():
            raise AppError("file_missing", "原文件已丢失", 404)
        return FileResponse(
            path,
            filename=doc.name,
            media_type="application/pdf" if doc.file_type == "pdf" else None,
            content_disposition_type="inline" if doc.file_type == "pdf" else "attachment",
        )
