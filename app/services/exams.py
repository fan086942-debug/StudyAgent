import hashlib
import logging
import re
import unicodedata
from pathlib import Path
from threading import Lock

from sqlalchemy import delete, or_, select, update

from app.core.errors import AppError
from app.models import Course, Document, ExamPaper, KnowledgePoint, Question, QuestionKnowledgePoint
from app.rag.parsers import parse_document
from app.schemas.exam import PaperOut, QuestionOut, QuestionSearch
from app.services.exam_parser import (
    build_exam_text,
    extraction_windows,
    locate_quote,
    rule_extract,
    verify_number,
)

logger = logging.getLogger("studyagent")


def normalize_point(name: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", name)).casefold()


class ExamService:
    def __init__(self, settings, sessions, extractor):
        self.settings, self.sessions, self.extractor = settings, sessions, extractor
        self.lock = Lock()

    def recover_interrupted(self):
        with self.sessions() as session:
            session.execute(
                update(ExamPaper)
                .where(ExamPaper.status == "processing")
                .values(status="failed", error="上次题目解析被中断，请重新解析")
            )
            session.commit()

    def validate_scope(self, course_id: str, document_ids: list[str] | None) -> None:
        with self.sessions() as session:
            if session.get(Course, course_id) is None:
                raise AppError("course_not_found", "课程不存在", 404)
            if document_ids is not None:
                owned = set(
                    session.scalars(select(Document.id).where(Document.course_id == course_id))
                )
                if not document_ids or not set(document_ids).issubset(owned):
                    raise AppError("invalid_scope", "选择的资料不存在或不属于当前课程", 400)

    def extract(self, document_id: str) -> PaperOut:
        if not self.lock.acquire(blocking=False):
            raise AppError("exam_busy", "已有试卷正在解析，请稍后重试", 409)
        try:
            return self._extract(document_id)
        finally:
            self.lock.release()

    def _extract(self, document_id: str) -> PaperOut:
        with self.sessions() as session:
            doc = session.get(Document, document_id)
            if doc is None:
                raise AppError("document_not_found", "资料不存在", 404)
            if doc.document_type != "exam" or doc.status != "ready":
                raise AppError("invalid_exam", "请先将资料作为试卷上传并完成索引", 409)
            paper = session.scalar(select(ExamPaper).where(ExamPaper.document_id == document_id))
            if paper is None:
                paper = ExamPaper(document_id=doc.id, course_id=doc.course_id)
                session.add(paper)
            paper.status, paper.error = "processing", None
            session.commit()
            try:
                parsed = build_exam_text(
                    parse_document(
                        Path(doc.storage_path),
                        settings=self.settings,
                        cache_dir=self.settings.data_dir / "ocr" / document_id,
                        digest=doc.sha256,
                    ).blocks
                )
                candidates = []
                if self.settings.study_mode == "demo":
                    cursor = 0
                    for item in rule_extract(parsed.text):
                        start, end = locate_quote(parsed.text, item.source_text, cursor)
                        candidates.append((start, end, item))
                        cursor = end
                else:
                    windows = extraction_windows(parsed.text, self.settings.exam_batch_chars)
                    if len(windows) > self.settings.exam_max_batches:
                        raise AppError(
                            "exam_too_large", "试卷超过模型解析批次上限，请拆分文件", 413
                        )
                    for offset, window in windows:
                        cursor = 0
                        for item in self.extractor.extract(window).questions:
                            start, end = locate_quote(window, item.source_text, cursor)
                            candidates.append((offset + start, offset + end, item))
                            cursor = end
                if not candidates:
                    raise AppError(
                        "exam_no_questions",
                        "未识别到题目；演示模式需清晰数字题号，复杂版式请使用 API 模式",
                    )
                # 先完成并校验全部抽取，再在一个事务中替换题库；失败不会留下半套试卷。
                session.execute(delete(Question).where(Question.paper_id == paper.id))
                accepted = []
                for start, end, item in sorted(candidates, key=lambda row: row[0]):
                    if any(start < b and end > a for a, b in accepted):
                        continue  # 重叠窗口召回同一题时只保存一次。
                    for option in item.options:
                        locate_quote(item.source_text, option)
                    verify_number(item.number, item.source_text)
                    ordinal = len(accepted)
                    question = Question(
                        id=hashlib.sha256(f"{paper.id}:{start}:{end}".encode()).hexdigest(),
                        paper_id=paper.id,
                        ordinal=ordinal,
                        number=item.number,
                        type=item.type,
                        content=parsed.text[start:end],
                        options=item.options,
                        score=item.score,
                        difficulty=item.difficulty,
                        locations=parsed.locations(start, end),
                    )
                    session.add(question)
                    session.flush()
                    seen = set()
                    for name in item.knowledge_points:
                        name = name.strip()
                        normalized = normalize_point(name)
                        if not normalized or len(name) > 120 or len(normalized) > 120:
                            raise AppError(
                                "exam_invalid_point", "知识点标签长度不合法，请重试", 502
                            )
                        if normalized in seen:
                            continue
                        seen.add(normalized)
                        point = session.scalar(
                            select(KnowledgePoint).where(
                                KnowledgePoint.course_id == doc.course_id,
                                KnowledgePoint.normalized_name == normalized,
                            )
                        )
                        if point is None:
                            point = KnowledgePoint(
                                course_id=doc.course_id, name=name, normalized_name=normalized
                            )
                            session.add(point)
                            session.flush()
                        session.add(
                            QuestionKnowledgePoint(
                                question_id=question.id, knowledge_point_id=point.id
                            )
                        )
                    accepted.append((start, end))
                paper.status, paper.question_count = "ready", len(accepted)
                paper.extraction_method = "rules" if self.settings.study_mode == "demo" else "llm"
                paper.warning = (
                    "规则解析仅识别常见数字题号；知识点仅提取【知识点：…】标签，难度未评估。请核对原卷。"
                    if self.settings.study_mode == "demo"
                    else "题型、知识点和难度由模型标注，请核对原卷；超长跨窗口题目可能遗漏。"
                )
                session.commit()
                logger.info(
                    "exam document=%s questions=%s method=%s",
                    doc.id,
                    paper.question_count,
                    paper.extraction_method,
                )
                return self._paper_out(paper, doc)
            except Exception as exc:
                session.rollback()
                paper.status, paper.error = (
                    "failed",
                    exc.message if isinstance(exc, AppError) else "试卷解析失败，请重试",
                )
                session.commit()
                if isinstance(exc, AppError):
                    raise
                raise AppError("exam_failed", "试卷解析失败，请重试", 500) from exc

    @staticmethod
    def _paper_out(paper, doc) -> PaperOut:
        return PaperOut(
            id=paper.id,
            document_id=doc.id,
            name=doc.name,
            status=paper.status,
            error=paper.error,
            warning=paper.warning,
            question_count=paper.question_count,
            extraction_method=paper.extraction_method,
        )

    def papers(self, course_id: str) -> list[PaperOut]:
        self.validate_scope(course_id, None)
        with self.sessions() as session:
            return [
                self._paper_out(paper, doc)
                for paper, doc in session.execute(
                    select(ExamPaper, Document)
                    .join(Document, Document.id == ExamPaper.document_id)
                    .where(ExamPaper.course_id == course_id)
                    .order_by(ExamPaper.created_at.desc())
                )
            ]

    @staticmethod
    def _question_out(session, question, paper, doc) -> QuestionOut:
        points = list(
            session.scalars(
                select(KnowledgePoint.name)
                .join(QuestionKnowledgePoint)
                .where(QuestionKnowledgePoint.question_id == question.id)
            )
        )
        page = question.locations[0].get("page") if question.locations else None
        return QuestionOut(
            id=question.id,
            paper_id=paper.id,
            document_id=doc.id,
            paper_name=doc.name,
            file_type=doc.file_type,
            number=question.number,
            type=question.type,
            content=question.content,
            options=question.options,
            score=question.score,
            difficulty=question.difficulty,
            knowledge_points=points,
            locations=question.locations,
            extraction_method=paper.extraction_method,
            file_url=f"/api/documents/{doc.id}/file"
            + (f"#page={page}" if doc.file_type == "pdf" and page else ""),
        )

    @staticmethod
    def _query(course_id, document_ids):
        statement = (
            select(Question, ExamPaper, Document)
            .join(ExamPaper, ExamPaper.id == Question.paper_id)
            .join(Document, Document.id == ExamPaper.document_id)
            .where(
                ExamPaper.course_id == course_id,
                ExamPaper.status == "ready",
                Document.status == "ready",
            )
        )
        if document_ids is not None:
            statement = statement.where(Document.id.in_(document_ids))
        return statement

    def search(
        self, course_id: str, document_ids: list[str] | None, args: QuestionSearch
    ) -> list[QuestionOut]:
        self.validate_scope(course_id, document_ids)
        statement = self._query(course_id, document_ids)
        for value, column in [
            (args.paper_id, ExamPaper.id),
            (args.number, Question.number),
            (args.question_type, Question.type),
        ]:
            if value is not None:
                statement = statement.where(column == value)
        if args.paper_name:
            statement = statement.where(Document.name.contains(args.paper_name, autoescape=True))
        point_ids = select(QuestionKnowledgePoint.question_id).join(KnowledgePoint)
        if args.knowledge_point:
            statement = statement.where(
                Question.id.in_(
                    point_ids.where(
                        KnowledgePoint.normalized_name.contains(
                            normalize_point(args.knowledge_point), autoescape=True
                        )
                    )
                )
            )
        if args.query.strip():
            # 第一版题库用字面检索与知识点关联，保留准确题号；语义题目召回可后续扩展。
            tokens = args.query.strip().split()[:12]
            statement = statement.where(
                or_(
                    *[
                        or_(
                            Question.content.icontains(token, autoescape=True),
                            Question.id.in_(
                                point_ids.where(
                                    KnowledgePoint.normalized_name.contains(
                                        normalize_point(token), autoescape=True
                                    )
                                )
                            ),
                        )
                        for token in tokens
                    ]
                )
            )
        with self.sessions() as session:
            return [
                self._question_out(session, *row)
                for row in session.execute(
                    statement.order_by(Document.created_at.desc(), Question.ordinal).limit(
                        args.limit
                    )
                )
            ]

    def get(self, course_id: str, document_ids: list[str] | None, question_id: str) -> QuestionOut:
        self.validate_scope(course_id, document_ids)
        with self.sessions() as session:
            row = session.execute(
                self._query(course_id, document_ids).where(Question.id == question_id)
            ).first()
            if row is None:
                raise AppError(
                    "question_not_found", "当前课程和所选资料中未找到该题，请先搜索题库", 404
                )
            return self._question_out(session, *row)
