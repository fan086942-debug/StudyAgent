import hashlib
import logging
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, File, Form, Request, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.errors import AppError
from app.models import Course, Document
from app.schemas.document import DocumentOut, DocumentType

router = APIRouter(prefix="/api", tags=["documents"])
logger = logging.getLogger("studyagent")


def process_uploaded(state, identifier):
    try:
        state.ingestion.process(identifier)
    except Exception as exc:
        with state.ingestion.control_lock, state.sessions() as session:
            doc = session.get(Document, identifier)
            if doc is not None and doc.status in {"processing", "cancelling"}:
                cancelled = doc.status == "cancelling" or (
                    isinstance(exc, AppError) and exc.code == "processing_cancelled"
                )
                doc.status, doc.warning = "cancelled" if cancelled else "failed", None
                doc.error = (
                    "处理已取消，原文件和已识别页缓存已保留，可重试继续"
                    if cancelled
                    else exc.message
                    if isinstance(exc, AppError)
                    else "后台处理失败，请重试"
                )
                session.commit()
        logger.warning(
            "background_ingestion document=%s error=%s",
            identifier,
            exc.code if isinstance(exc, AppError) else type(exc).__name__,
        )
    finally:
        state.connection.leave_request()


def queue_document(request, identifier, tasks, response):
    state = request.state.services
    if state.ingestion.lock.locked():
        raise AppError("ingestion_busy", "已有资料正在处理，请稍后重试", 409)
    with state.ingestion.control_lock, state.sessions() as session:
        doc = session.get(Document, identifier)
        if doc is None:
            raise AppError("document_not_found", "资料不存在", 404)
        if doc.status == "cancelling" or (doc.status in {"deleting", "processing"} and doc.warning):
            raise AppError("document_busy", "资料正在处理或删除，请稍后再操作", 409)
        if doc.status == "deleting":
            raise AppError("document_deleting", "资料正在删除，请重试删除而不是重新索引", 409)
        doc.status, doc.error, doc.warning = "processing", None, "已接收资料，等待后台解析…"
        session.commit()
    # Keep model switching/course deletion guarded beyond the HTTP response.
    state.connection.enter_request()
    tasks.add_task(process_uploaded, state, identifier)
    response.status_code = 202
    return doc


@router.get("/courses/{course_id}/documents", response_model=list[DocumentOut])
def list_documents(course_id: str, request: Request):
    with request.state.services.sessions() as session:
        if session.get(Course, course_id) is None:
            raise AppError("course_not_found", "课程不存在", 404)
        return list(
            session.scalars(
                select(Document)
                .where(Document.course_id == course_id)
                .order_by(Document.created_at.desc())
            )
        )


@router.post(
    "/courses/{course_id}/documents",
    response_model=DocumentOut,
    status_code=201,
    responses={202: {"model": DocumentOut, "description": "已接收资料，后台处理进行中"}},
)
def upload_document(
    course_id: str,
    request: Request,
    file: UploadFile = File(...),
    document_type: DocumentType = Form("other"),
    background_tasks: BackgroundTasks = None,
    response: Response = None,
    background: Annotated[bool, Form()] = False,
):
    settings = request.state.services.settings
    name = (file.filename or "upload").replace("\\", "/").split("/")[-1][:255]
    suffix = Path(name).suffix.lower()
    if suffix not in {".pdf", ".pptx", ".docx"}:
        raise AppError("unsupported_type", "仅支持 PDF、PPTX、DOCX；PPT/DOC 请先转换", 415)
    with request.state.services.sessions() as session:
        if session.get(Course, course_id) is None:
            raise AppError("course_not_found", "课程不存在", 404)
        if request.state.services.ingestion.lock.locked():
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
        if background:
            return queue_document(request, identifier, background_tasks, response)
        return request.state.services.ingestion.process(identifier)
    except AppError as exc:
        # 与另一个上传恰好竞争时，已保存的文件应能重试，而非永远 processing。
        if exc.code == "ingestion_busy":
            with request.state.services.sessions() as session:
                doc = session.get(Document, identifier)
                doc.status, doc.error = "failed", exc.message
                session.commit()
        raise


@router.post(
    "/documents/{document_id}/retry",
    response_model=DocumentOut,
    responses={202: {"model": DocumentOut, "description": "后台重试进行中"}},
)
def retry(
    document_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    response: Response,
    background: bool = False,
):
    if background:
        return queue_document(request, document_id, background_tasks, response)
    with request.state.services.sessions() as session:
        doc = session.get(Document, document_id)
        if doc is not None and (
            doc.status == "cancelling" or (doc.status == "processing" and doc.warning)
        ):
            raise AppError("document_busy", "资料正在处理或停止中，请稍后再重试", 409)
    return request.state.services.ingestion.process(document_id)


@router.delete("/documents/{document_id}")
def delete_document(document_id: str, request: Request):
    return request.state.services.ingestion.delete(document_id)


@router.post("/documents/{document_id}/cancel", response_model=DocumentOut, status_code=202)
def cancel_processing(document_id: str, request: Request):
    return request.state.services.ingestion.cancel(document_id)


@router.get("/documents/{document_id}/file")
def download(document_id: str, request: Request):
    with request.state.services.sessions() as session:
        doc = session.get(Document, document_id)
        if doc is None:
            raise AppError("document_not_found", "资料不存在", 404)
        if doc.status == "deleting":
            raise AppError("document_deleting", "资料已停止使用，正在删除", 409)
        path = Path(doc.storage_path).resolve()
        if not path.is_relative_to((request.state.services.settings.data_dir / "uploads").resolve()):
            raise AppError("invalid_file_path", "资料存储路径异常", 500)
        if not path.exists():
            raise AppError("file_missing", "原文件已丢失", 404)
        return FileResponse(
            path,
            filename=doc.name,
            media_type="application/pdf" if doc.file_type == "pdf" else None,
            content_disposition_type="inline" if doc.file_type == "pdf" else "attachment",
        )
