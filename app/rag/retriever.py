import re
import time

from sqlalchemy import func, select

from app.core.errors import AppError
from app.models import Course, Document, DocumentChunk
from app.rag.sources import chunk_source
from app.schemas.chat import SearchRequest, SearchResponse


class Retriever:
    def __init__(self, settings, sessions, embeddings, vectors):
        self.settings, self.sessions = settings, sessions
        self.embeddings, self.vectors = embeddings, vectors

    def search(self, request: SearchRequest) -> SearchResponse:
        start = time.perf_counter()
        with self.sessions() as session:
            ready = self._ready(session, request)
            if not ready:
                return SearchResponse(sources=[], retrieval_ms=(time.perf_counter() - start) * 1000)
            vector = self.embeddings.embed([request.question])[0]
            hits = self.vectors.search(
                vector, request.course_id, ready, self.settings.retrieval_candidates
            )
            sources, seen, budget = [], set(), self.settings.context_char_budget
            # Apply the similarity threshold before including a source in the context budget.
            for chunk_id, distance in hits:
                score = 1 - float(distance)
                if score < self.settings.min_similarity:
                    continue
                row = session.execute(
                    select(DocumentChunk, Document)
                    .join(Document, Document.id == DocumentChunk.document_id)
                    .where(
                        DocumentChunk.id == chunk_id,
                        Document.course_id == request.course_id,
                        Document.status == "ready",
                        Document.id.in_(ready),
                        Document.embedding_fingerprint == self.embeddings.fingerprint,
                    )
                ).first()
                if row is None:
                    continue
                chunk, doc = row
                key = (doc.id, chunk.text)
                if key in seen:
                    continue
                if budget < 100:
                    break
                text = chunk.text[:budget]
                sources.append(
                    chunk_source(chunk, doc, f"S{len(sources) + 1}", score=score, text=text)
                )
                seen.add(key)
                budget -= len(text)
                if len(sources) == self.settings.retrieval_top_k:
                    break
        return SearchResponse(sources=sources, retrieval_ms=(time.perf_counter() - start) * 1000)

    def _ready(self, session, request):
        if session.get(Course, request.course_id) is None:
            raise AppError("course_not_found", "课程不存在", 404)
        docs = list(
            session.scalars(select(Document).where(Document.course_id == request.course_id))
        )
        owned_ids = {doc.id for doc in docs}
        if request.document_ids and not set(request.document_ids).issubset(owned_ids):
            raise AppError("invalid_scope", "选择的资料不存在或不属于当前课程", 400)
        ready = [
            doc.id
            for doc in docs
            if doc.status == "ready"
            and doc.embedding_fingerprint == self.embeddings.fingerprint
            and (request.document_ids is None or doc.id in request.document_ids)
        ]
        return ready

    def locate(self, request: SearchRequest) -> SearchResponse:
        """Literal locations do not depend on short-query vector similarity."""
        start = time.perf_counter()
        term = request.question.strip()
        if not 2 <= len(term) <= 80:
            return self.search(request)
        leading = r"(?<![a-zA-Z0-9_])" if term[0].isascii() and term[0].isalnum() else ""
        trailing = r"(?![a-zA-Z0-9_])" if term[-1].isascii() and term[-1].isalnum() else ""
        pattern = re.compile(leading + re.escape(term) + trailing, re.IGNORECASE)
        with self.sessions() as session:
            ready = self._ready(session, request)
            if not ready:
                return SearchResponse(sources=[], retrieval_ms=(time.perf_counter() - start) * 1000)
            rows = session.execute(
                select(DocumentChunk, Document)
                .join(Document, Document.id == DocumentChunk.document_id)
                .where(
                    DocumentChunk.document_id.in_(ready),
                    func.lower(DocumentChunk.text).contains(term.lower(), autoescape=True),
                )
                .order_by(DocumentChunk.document_id, DocumentChunk.ordinal)
                .limit(self.settings.retrieval_candidates * 4)
            )
            sources, seen, budget = [], set(), self.settings.context_char_budget
            for chunk, doc in rows:
                if not pattern.search(chunk.text) or (doc.id, chunk.text) in seen:
                    continue
                if budget < 100:
                    break
                # Keep the literal hit in the source if the remaining budget clips a long block.
                match = pattern.search(chunk.text)
                offset = max(0, match.start() - budget // 3)
                text = chunk.text[offset : offset + budget]
                sources.append(
                    chunk_source(chunk, doc, f"S{len(sources) + 1}", score=1.0, text=text)
                )
                seen.add((doc.id, chunk.text))
                budget -= len(text)
                if len(sources) == self.settings.retrieval_top_k:
                    break
            if sources:
                return SearchResponse(
                    sources=sources, retrieval_ms=(time.perf_counter() - start) * 1000
                )
        return self.search(request)
