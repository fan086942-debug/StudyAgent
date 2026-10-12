from contextlib import ExitStack
from pathlib import Path

from sqlalchemy import delete, select

from app.core.errors import AppError
from app.models import (
    Conversation,
    Course,
    Document,
    KnowledgePoint,
    PracticeAttempt,
    StudyArtifact,
    StudyPlan,
    WrongQuestion,
)


def delete_course(state, course_id: str):
    """Purge a course while the request gate excludes other business requests."""
    with ExitStack() as stack:
        for lock in [
            state.ingestion.lock,
            state.exams.lock,
            state.generation.lock,
            state.learning.lock,
        ]:
            if not lock.acquire(blocking=False):
                raise AppError("course_busy", "课程任务正在处理，请结束后再删除", 409)
            stack.callback(lock.release)
        with state.sessions() as session:
            if session.get(Course, course_id) is None:
                raise AppError("course_not_found", "课程不存在", 404)
            documents = list(
                session.scalars(select(Document).where(Document.course_id == course_id))
            )
            root = (state.settings.data_dir / "uploads").resolve()
            # Validate every path before touching any file; never delete a directory tree.
            for doc in documents:
                path = Path(doc.storage_path).resolve()
                if path.parent != root or path.name != f"{doc.id}.{doc.file_type}":
                    raise AppError("invalid_file_path", "资料存储路径异常，未执行课程删除", 500)
                if doc.status in {"processing", "cancelling"}:
                    raise AppError("course_busy", "课程资料正在处理，请结束后再删除", 409)
            document_ids = [doc.id for doc in documents]
        try:
            for document_id in document_ids:
                state.ingestion._delete_locked(document_id)
            with state.sessions() as session:
                for model in [
                    Conversation,
                    StudyPlan,
                    WrongQuestion,
                    PracticeAttempt,
                    StudyArtifact,
                    KnowledgePoint,
                ]:
                    session.execute(delete(model).where(model.course_id == course_id))
                session.execute(delete(Course).where(Course.id == course_id))
                session.commit()
        except Exception as exc:
            raise AppError(
                "course_delete_incomplete",
                "课程删除未完成，已清理的资料不会恢复；请重试删除课程",
                exc.status if isinstance(exc, AppError) else 500,
            ) from exc
    return {"deleted": course_id}
