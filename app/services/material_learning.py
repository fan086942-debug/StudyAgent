import re
import unicodedata

from sqlalchemy import select

from app.core.errors import AppError
from app.models import Document, DocumentChunk, Question, StudyArtifact
from app.rag.sources import chunk_source
from app.schemas.material_learning import MaterialQuestionLink, RelationResult
from app.services.exams import normalize_point


def tokens(text):
    # No language/model-specific dependency: use English words and Chinese bigrams.
    words = set(re.findall(r"[a-z][a-z0-9_*+-]{1,}", text.casefold()))
    words -= {
        "the",
        "and",
        "for",
        "what",
        "with",
        "this",
        "that",
        "explain",
        "describe",
        "define",
        "which",
        "following",
        "question",
        "answer",
    }
    for run in re.findall(r"[\u4e00-\u9fff]+", text):
        words.update(run[i : i + 2] for i in range(len(run) - 1))
    return words - {
        "是什么",
        "什么",
        "解释",
        "简述",
        "知识",
        "识点",
        "说明",
        "如何",
        "分析",
        "选择",
        "正确",
        "以下",
    }


def contains_point(text, point):
    original = unicodedata.normalize("NFKC", point).strip().casefold()
    point = normalize_point(point)
    if len(point) < 2:
        return False
    if re.fullmatch(r"[a-z0-9_*+-]+", point):
        return bool(
            re.search(
                r"(?<![a-z0-9_])"
                + r"\s*".join(re.escape(p) for p in original.split())
                + r"(?![a-z0-9_])",
                unicodedata.normalize("NFKC", text).casefold(),
            )
        )
    return point in normalize_point(text)


def current_source(source, chunk):
    # Chunk IDs are ordinal-based and can be reused after re-indexing; compare content/position too.
    return bool(
        chunk
        and chunk.text.startswith(source["text"])
        and all(
            source.get(field) == getattr(chunk, field)
            for field in (
                "document_id",
                "page",
                "chapter",
                "section",
                "block_index",
                "location_type",
            )
        )
    )


class MaterialLearningService:
    def __init__(self, sessions, exams, retriever):
        self.sessions, self.exams, self.retriever = sessions, exams, retriever

    def relations(self, course_id, request):
        self.exams.validate_scope(course_id, request.document_ids)
        self.exams.validate_scope(course_id, request.exam_document_ids)
        with self.sessions() as session:
            if request.material_id:
                doc = session.get(Document, request.material_id)
                if doc is None or doc.course_id != course_id or doc.document_type == "exam":
                    raise AppError("invalid_material", "对应的参考资料不存在或不属于当前课程", 404)
                if request.document_ids is not None and doc.id not in request.document_ids:
                    raise AppError("invalid_scope", "资料不在已选范围内", 400)
            statement = (
                select(DocumentChunk, Document)
                .join(Document)
                .where(
                    Document.course_id == course_id,
                    Document.document_type != "exam",
                    Document.status == "ready",
                    Document.embedding_fingerprint == self.retriever.embeddings.fingerprint,
                )
                .order_by(Document.id, DocumentChunk.ordinal)
            )
            if request.document_ids is not None:
                statement = statement.where(Document.id.in_(request.document_ids))
            if request.material_id:
                statement = statement.where(Document.id == request.material_id)
            rows = list(session.execute(statement))
            if request.artifact_id:
                artifact = session.get(StudyArtifact, request.artifact_id)
                if artifact is None or artifact.course_id != course_id:
                    raise AppError("artifact_not_found", "对应的学习记录不存在", 404)
                snapshots = {s["chunk_id"]: s for s in artifact.payload.get("sources", [])}
                requested = request.chunk_ids or list(snapshots)
                live_chunks = {c.id: c for c, _ in rows}
                if not requested or any(
                    c not in snapshots or not current_source(snapshots[c], live_chunks.get(c))
                    for c in requested
                ):
                    raise AppError(
                        "stale_knowledge",
                        "这份总结的依据已删除、重建或不在已选范围内，请重新总结后关联试题",
                        409,
                    )
                rows = [(c, d) for c, d in rows if c.id in requested]
            if request.chunk_ids:
                if not set(request.chunk_ids).issubset({c.id for c, _ in rows}):
                    raise AppError(
                        "invalid_scope", "知识点来源已删除、需要重建或不在已选范围内", 409
                    )
                rows = [(c, d) for c, d in rows if c.id in request.chunk_ids]
            if request.question_id:
                question = self.exams.get(course_id, request.exam_document_ids, request.question_id)
                questions = [question]
            else:
                questions = [
                    self.exams._question_out(session, q, p, d)
                    for q, p, d in session.execute(
                        self.exams._query(course_id, request.exam_document_ids).order_by(
                            Document.id, Question.ordinal
                        )
                    )
                ]
            if request.query.strip():
                query = request.query.strip()
                rows = [
                    (c, d)
                    for c, d in rows
                    if contains_point(c.text, query) or len(tokens(query) & tokens(c.text)) >= 2
                ]
            prepared = [(c, d, tokens(c.text)) for c, d in rows]
            candidates = []
            for question in questions:
                hits = []
                qtokens = tokens(question.content)
                for chunk, doc, ctokens in prepared:
                    concepts = [
                        p for p in question.knowledge_points if contains_point(chunk.text, p)
                    ]
                    if concepts:
                        method, score = (
                            "knowledge_label",
                            len(concepts) / max(1, len(question.knowledge_points)),
                        )
                    else:
                        shared = qtokens & ctokens
                        score = len(shared) / max(1, len(qtokens))
                        english = {
                            word for word in shared if re.fullmatch(r"[a-z][a-z0-9_*+-]+", word)
                        }
                        if (len(shared) < 4 and len(english) < 2) or score < 0.35:
                            continue
                        method, concepts = "text_overlap", []
                    hits.append((score, method, concepts, chunk, doc))
                if hits:
                    hits.sort(key=lambda h: (h[1] != "knowledge_label", -h[0], h[3].ordinal))
                    candidates.append((hits[0][0], question, hits[:3]))
            candidates.sort(key=lambda item: (item[2][0][1] != "knowledge_label", -item[0]))
            links, sources, linked_questions, seen = [], [], [], set()
            for score, question, hits in candidates[: request.limit]:
                linked_questions.append(question)
                links.append(
                    MaterialQuestionLink(
                        question_id=question.id,
                        chunk_ids=[h[3].id for h in hits],
                        concepts=list(dict.fromkeys(p for h in hits for p in h[2])),
                        method=hits[0][1],
                        score=round(score, 4),
                    )
                )
                for _, _, _, chunk, doc in hits:
                    if chunk.id not in seen:
                        seen.add(chunk.id)
                        sources.append(chunk_source(chunk, doc, f"S{len(sources) + 1}"))
            if links:
                answer = f"找到 {len(links)} 道试题与 {len(sources)} 处资料的学习关联，可查看原题和教材/课件依据。"
            elif not rows:
                answer = "当前范围没有可匹配的教材或课件正文，请确认资料已完成处理，或调整知识点/资料范围。"
            elif not questions:
                answer = "当前试卷范围还没有已解析题目。可上传试卷并完成题目解析；若要根据资料生成新卷，请使用「整份资料学习包」。"
            else:
                answer = "已检查当前资料与题库，尚未发现可展示的关联。可以缩小到具体知识点，或在 API 模式重新解析试卷的知识点标签。"
            return RelationResult(
                direction=request.direction,
                answer=answer,
                links=links,
                sources=sources,
                questions=linked_questions,
                warning="知识点标签匹配与文本相似均为候选学习关联，请核对原文；关联不等于题目答案或官方考点。",
            )

    def knowledge(self, course_id, document_id=None):
        """Project saved summaries; deleted/rebuilt sources never re-enter the active library."""
        self.exams.validate_scope(course_id, [document_id] if document_id else None)
        with self.sessions() as session:
            live = {
                chunk.id: chunk
                for chunk in session.scalars(
                    select(DocumentChunk)
                    .join(Document)
                    .where(
                        Document.course_id == course_id,
                        Document.document_type != "exam",
                        Document.status == "ready",
                        Document.embedding_fingerprint == self.retriever.embeddings.fingerprint,
                    )
                )
            }
            result, seen = [], set()
            artifacts = session.scalars(
                select(StudyArtifact)
                .where(StudyArtifact.course_id == course_id)
                .order_by(StudyArtifact.created_at.desc(), StudyArtifact.id)
            )
            for artifact in artifacts:
                lookup = {s["citation_id"]: s for s in artifact.payload.get("sources", [])}
                for section in artifact.payload.get("content", {}).get("sections", []):
                    refs = [lookup[c] for c in section["citation_ids"] if c in lookup]
                    # A summary supported partly by removed sources is historical, not current knowledge.
                    if not refs or any(
                        not current_source(s, live.get(s["chunk_id"])) for s in refs
                    ):
                        continue
                    if document_id and not any(s["document_id"] == document_id for s in refs):
                        continue
                    key = (section["topic"], tuple(sorted({s["document_id"] for s in refs})))
                    if key in seen:
                        continue
                    seen.add(key)
                    result.append(
                        dict(artifact_id=artifact.id, mode=artifact.mode, **section, sources=refs)
                    )
            return result
