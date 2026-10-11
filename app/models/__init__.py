from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import JSON, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def new_id() -> str:
    return uuid4().hex


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Base(DeclarativeBase):
    pass


class StudyArtifact(Base):
    __tablename__ = "study_artifacts"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(120))
    mode: Mapped[str] = mapped_column(String(10))
    warning: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(default=utc_now)


class Course(Base):
    __tablename__ = "courses"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[str] = mapped_column(default=utc_now)


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("course_id", "sha256"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[str] = mapped_column(String(10))
    document_type: Mapped[str] = mapped_column(String(20))
    sha256: Mapped[str] = mapped_column(String(64))
    storage_path: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(default="processing")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    warning: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunk_count: Mapped[int] = mapped_column(default=0)
    embedding_fingerprint: Mapped[str | None] = mapped_column(nullable=True)
    created_at: Mapped[str] = mapped_column(default=utc_now)


class DocumentChunk(Base):
    __tablename__ = "chunks"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), index=True)
    ordinal: Mapped[int]
    text: Mapped[str] = mapped_column(Text)
    page: Mapped[int | None] = mapped_column(nullable=True)
    chapter: Mapped[str | None] = mapped_column(nullable=True)
    section: Mapped[str | None] = mapped_column(nullable=True)
    block_index: Mapped[int]
    location_type: Mapped[str]


class ExamPaper(Base):
    __tablename__ = "exam_papers"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), unique=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), index=True)
    status: Mapped[str] = mapped_column(default="processing")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    warning: Mapped[str | None] = mapped_column(Text, nullable=True)
    extraction_method: Mapped[str] = mapped_column(default="rules")
    question_count: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[str] = mapped_column(default=utc_now)


class Question(Base):
    __tablename__ = "questions"
    __table_args__ = (UniqueConstraint("paper_id", "ordinal"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    paper_id: Mapped[str] = mapped_column(ForeignKey("exam_papers.id"), index=True)
    ordinal: Mapped[int]
    # 同一试卷不同大题可能都从 1 开始，number 不是唯一键。
    number: Mapped[str] = mapped_column(String(64))
    type: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    options: Mapped[list] = mapped_column(JSON)
    score: Mapped[float | None] = mapped_column(nullable=True)
    difficulty: Mapped[str] = mapped_column(default="unknown")
    # 位置只取自解析器；模型负责识别文本，不能自己生成页码。
    locations: Mapped[list] = mapped_column(JSON)


class KnowledgePoint(Base):
    __tablename__ = "knowledge_points"
    __table_args__ = (UniqueConstraint("course_id", "normalized_name"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    normalized_name: Mapped[str] = mapped_column(String(120))


class QuestionKnowledgePoint(Base):
    __tablename__ = "question_knowledge_points"
    # 多对多关联：一道题可涉及多个知识点，同一知识点可出现在多套卷子中。
    question_id: Mapped[str] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), primary_key=True
    )
    knowledge_point_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_points.id"), primary_key=True
    )


class PracticeAttempt(Base):
    __tablename__ = "practice_attempts"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), index=True)
    reference_key: Mapped[str] = mapped_column(String(160))
    snapshot: Mapped[dict] = mapped_column(JSON)
    answer: Mapped[str] = mapped_column(Text, default="")
    outcome: Mapped[str] = mapped_column(String(10))
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[str] = mapped_column(default=utc_now)


class WrongQuestion(Base):
    __tablename__ = "wrong_questions"
    __table_args__ = (UniqueConstraint("course_id", "reference_key"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), index=True)
    reference_key: Mapped[str] = mapped_column(String(160))
    snapshot: Mapped[dict] = mapped_column(JSON)
    answer: Mapped[str] = mapped_column(Text, default="")
    note: Mapped[str] = mapped_column(Text, default="")
    wrong_count: Mapped[int] = mapped_column(default=0)
    mastered: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[str] = mapped_column(default=utc_now)


class StudyPlan(Base):
    __tablename__ = "study_plans"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), index=True)
    title: Mapped[str] = mapped_column(String(120))
    topics: Mapped[list] = mapped_column(JSON)
    document_ids: Mapped[list] = mapped_column(JSON)
    daily_minutes: Mapped[int]
    tasks: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(default=utc_now)


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), index=True)
    question: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(10))
    document_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(default=utc_now)
