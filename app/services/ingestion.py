import hashlib
import logging
from contextlib import ExitStack
from pathlib import Path
from threading import Lock, RLock

from sqlalchemy import delete, or_, select, update

from app.core.errors import AppError
from app.models import (
    Document,
    DocumentChunk,
    ExamPaper,
    KnowledgePoint,
    Question,
    QuestionKnowledgePoint,
)
from app.rag.chunker import chunk_blocks
from app.rag.parsers import parse_document
from app.rag.parsers.ocr import delete_ocr_cache
from app.services.study_checkpoint import purge_study_cache

logger = logging.getLogger("studyagent")


class IngestionService:
    def __init__(self, settings, sessions, embeddings, vectors, exams=None):
        self.settings, self.sessions = settings, sessions
        self.embeddings, self.vectors = embeddings, vectors
        self.exams = exams
        self.lock = Lock()
        self.control_lock = RLock()

    def check_cancelled(self, document_id: str):
        with self.sessions() as session:
            state = session.scalar(select(Document.status).where(Document.id == document_id))
        if state == "cancelling":
            raise AppError(
                "processing_cancelled", "处理已取消，原文件和已识别页缓存已保留，可重试继续", 409
            )

    def cancel(self, document_id: str):
        # Serialize cancellation with progress/final commits.
        with self.control_lock, self.sessions() as session:
            document = session.get(Document, document_id)
            if document is None:
                raise AppError("document_not_found", "资料不存在", 404)
            if document.status == "cancelled":
                return document
            if document.status not in {"processing", "cancelling"}:
                raise AppError("document_not_processing", "资料当前未在处理中，无需取消", 409)
            document.status = "cancelling"
            document.warning = "正在停止处理，请等待当前页或接口请求结束；已识别页缓存会保留"
            session.commit()
            return document

    def recover_interrupted(self):
        with self.sessions() as session:
            session.execute(
                update(Document)
                .where(Document.status.in_(["processing", "cancelling"]))
                .values(status="failed", error="上次处理被中断，请点击重试")
            )
            session.commit()

    def process(self, document_id: str):
        if not self.lock.acquire(blocking=False):
            raise AppError("ingestion_busy", "已有资料正在处理，请稍后重试", 409)
        try:
            document = self._process(document_id)
            if self.exams is not None and document.document_type == "exam":
                try:
                    self.exams.extract(document_id)
                except AppError as exc:
                    # 试卷结构化有独立状态和重试入口，失败不撤销已经可用的 RAG 索引。
                    logger.warning("exam_extract document=%s error=%s", document_id, exc.code)
            return document
        finally:
            self.lock.release()

    def _process(self, document_id: str):
        with self.sessions() as session:
            document = session.get(Document, document_id)
            if document is None:
                raise AppError("document_not_found", "资料不存在", 404)
            if document.status == "deleting":
                raise AppError("document_deleting", "资料正在删除，请重试删除而不是重新索引", 409)
            with self.control_lock:
                session.refresh(document)
                if document.status != "cancelling":
                    document.status, document.error, document.warning = (
                        "processing",
                        None,
                        "正在解析资料…",
                    )
                    session.commit()
            try:
                self.check_cancelled(document_id)
                self.vectors.delete_document(document_id)
                session.execute(
                    delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
                )
                session.commit()

                # 入库链路：解析带位置的文本块 → 分块 → 向量化 → 写入向量索引及正文。
                def report_progress(page, total, phase):
                    with self.control_lock:
                        self.check_cancelled(document_id)
                        document.warning = (
                            f"正在本地 OCR · 第 {page} / {total} 页；识别完成后自动建立索引"
                            if phase == "ocr"
                            else f"正在读取 PDF · 第 {page} / {total} 页"
                        )
                        session.commit()

                parsed = parse_document(
                    Path(document.storage_path),
                    settings=self.settings,
                    cache_dir=self.settings.data_dir / "ocr" / document_id,
                    digest=document.sha256,
                    progress=report_progress,
                    cancel=lambda: self.check_cancelled(document_id),
                )
                self.check_cancelled(document_id)
                pieces = chunk_blocks(
                    parsed.blocks, self.settings.chunk_size, self.settings.chunk_overlap
                )
                if not pieces:
                    raise AppError("no_text", "清理后没有可索引文本")
                chunks = [
                    DocumentChunk(
                        id=hashlib.sha256(f"{document_id}:{index}".encode()).hexdigest(),
                        document_id=document_id,
                        course_id=document.course_id,
                        ordinal=index,
                        **piece.model_dump(),
                    )
                    for index, piece in enumerate(pieces)
                ]
                embeddings = []
                for start in range(0, len(chunks), 16):
                    with self.control_lock:
                        self.check_cancelled(document_id)
                        document.warning = f"正在建立索引 · {start} / {len(chunks)} 个片段"
                        session.commit()
                    embeddings.extend(
                        self.embeddings.embed([chunk.text for chunk in chunks[start : start + 16]])
                    )
                    self.check_cancelled(document_id)
                for start in range(0, len(chunks), 100):
                    self.check_cancelled(document_id)
                    self.vectors.add(chunks[start : start + 100], embeddings[start : start + 100])
                # 向量写入成功后提交正文与 ready 状态，使检索只读取已完成索引的资料。
                with self.control_lock:
                    self.check_cancelled(document_id)
                    session.add_all(chunks)
                    document.chunk_count = len(chunks)
                    document.warning = "；".join(parsed.warnings) or None
                    document.embedding_fingerprint = self.embeddings.fingerprint
                    document.status = "ready"
                    session.commit()
                logger.info(
                    "ingestion document=%s chunks=%s status=ready", document_id, len(chunks)
                )
                return document
            except Exception as exc:
                session.rollback()
                # Chroma 与关系数据库不共享事务，失败时需额外清理可能已写入的向量。
                try:
                    self.vectors.delete_document(document_id)
                except AppError:
                    logger.error("index_cleanup_failed document=%s", document_id)
                with self.control_lock:
                    document = session.get(Document, document_id)
                    cancelled = document.status == "cancelling" or (
                        isinstance(exc, AppError) and exc.code == "processing_cancelled"
                    )
                    document.status, document.chunk_count = (
                        "cancelled" if cancelled else "failed",
                        0,
                    )
                    session.execute(
                        delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
                    )
                    document.warning = None
                    document.error = (
                        "处理已取消，原文件和已识别页缓存已保留，可重试继续"
                        if cancelled
                        else exc.message
                        if isinstance(exc, AppError)
                        else "资料处理失败，请重试"
                    )
                    session.commit()
                if isinstance(exc, AppError):
                    raise
                raise AppError("ingestion_failed", "资料处理失败，请重试", 500) from exc

    def delete(self, document_id: str):
        with ExitStack() as stack:
            locks = [self.lock] + ([self.exams.lock] if self.exams else [])
            for lock in locks:
                if not lock.acquire(blocking=False):
                    raise AppError("document_busy", "资料正在上传、重建或解析，请结束后再删除", 409)
                stack.callback(lock.release)
            return self._delete_locked(document_id)

    def _delete_locked(self, document_id: str):
        """Caller owns ingestion/extraction locks (also used by course deletion)."""
        with self.sessions() as session:
            document = session.get(Document, document_id)
            if document is None:
                raise AppError("document_not_found", "资料不存在", 404)
            if document.status in {"processing", "cancelling"}:
                raise AppError("document_busy", "资料正在处理，请结束后再删除", 409)
            path = Path(document.storage_path).resolve()
            upload_root = (self.settings.data_dir / "uploads").resolve()
            if path.parent != upload_root or path.name != f"{document.id}.{document.file_type}":
                raise AppError("invalid_file_path", "资料存储路径异常，未执行删除", 500)
            # A partial failure must not leave a searchable ready document with
            # missing file/vectors. The deleting state supports a safe retry.
            document.status, document.error = "deleting", None
            session.commit()
            try:
                self.vectors.delete_document_everywhere(document_id)
                path.unlink(missing_ok=True)
                delete_ocr_cache(self.settings.data_dir, document_id)
                purge_study_cache(self.settings.data_dir, document.course_id, document_id)
                paper_ids = select(ExamPaper.id).where(ExamPaper.document_id == document_id)
                session.execute(delete(Question).where(Question.paper_id.in_(paper_ids)))
                session.execute(delete(ExamPaper).where(ExamPaper.document_id == document_id))
                session.execute(
                    delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
                )
                session.execute(
                    delete(KnowledgePoint).where(
                        KnowledgePoint.course_id == document.course_id,
                        ~KnowledgePoint.id.in_(select(QuestionKnowledgePoint.knowledge_point_id)),
                    )
                )
                session.delete(document)
                session.commit()
            except Exception as exc:
                session.rollback()
                remaining = session.get(Document, document_id)
                if remaining:
                    remaining.status = "deleting"
                    remaining.error = "删除未完成，资料已停止检索；请点击删除重试。"
                    session.commit()
                if isinstance(exc, AppError):
                    raise
                raise AppError("document_delete_failed", "删除未完成，请重试删除资料", 500) from exc
        return {"deleted": document_id}

    def mark_stale(self):
        with self.sessions() as session:
            session.execute(
                update(Document)
                .where(
                    Document.status == "ready",
                    or_(Document.embedding_fingerprint.is_(None),
                        Document.embedding_fingerprint != self.embeddings.fingerprint),
                )
                .values(status="stale", error="Embedding 配置已改变，请重新索引")
            )
            session.commit()
