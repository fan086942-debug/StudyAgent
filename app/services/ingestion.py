import hashlib
import logging
from pathlib import Path
from threading import Lock

from sqlalchemy import delete, select, update

from app.core.errors import AppError
from app.models import Document, DocumentChunk
from app.rag.chunker import chunk_blocks
from app.rag.parsers import parse_document

logger = logging.getLogger("studyagent")


class IngestionService:
    def __init__(self, settings, sessions, embeddings, vectors):
        self.settings, self.sessions = settings, sessions
        self.embeddings, self.vectors = embeddings, vectors
        self.lock = Lock()

    def recover_interrupted(self):
        with self.sessions() as session:
            session.execute(
                update(Document)
                .where(Document.status == "processing")
                .values(status="failed", error="上次处理被中断，请点击重试")
            )
            session.commit()

    def process(self, document_id: str):
        if not self.lock.acquire(blocking=False):
            raise AppError("ingestion_busy", "已有资料正在处理，请稍后重试", 409)
        try:
            return self._process(document_id)
        finally:
            self.lock.release()

    def _process(self, document_id: str):
        with self.sessions() as session:
            document = session.get(Document, document_id)
            if document is None:
                raise AppError("document_not_found", "资料不存在", 404)
            document.status, document.error = "processing", None
            session.commit()
            try:
                self.vectors.delete_document(document_id)
                session.execute(
                    delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
                )
                session.commit()
                parsed = parse_document(Path(document.storage_path))
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
                embeddings = self.embeddings.embed([chunk.text for chunk in chunks])
                self.vectors.add(chunks, embeddings)
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
                try:
                    self.vectors.delete_document(document_id)
                except AppError:
                    logger.error("index_cleanup_failed document=%s", document_id)
                document = session.get(Document, document_id)
                document.status, document.chunk_count = "failed", 0
                document.error = (
                    exc.message if isinstance(exc, AppError) else "资料处理失败，请重试"
                )
                session.commit()
                if isinstance(exc, AppError):
                    raise
                raise AppError("ingestion_failed", "资料处理失败，请重试", 500) from exc

    def mark_stale(self):
        with self.sessions() as session:
            docs = session.scalars(select(Document).where(Document.status == "ready"))
            for doc in docs:
                if doc.embedding_fingerprint != self.embeddings.fingerprint:
                    doc.status, doc.error = "stale", "Embedding 配置已改变，请重新索引"
            session.commit()
