from fastapi import APIRouter, Request
from sqlalchemy import select

from app.agent.tools import ToolContext
from app.models import KnowledgePoint, QuestionKnowledgePoint
from app.schemas.agent import ToolResult
from app.schemas.chat import SearchRequest
from app.schemas.exam import PaperOut, QuestionOut, QuestionSearch

router = APIRouter(prefix="/api", tags=["exams"])


@router.get("/courses/{course_id}/papers", response_model=list[PaperOut])
def papers(course_id: str, request: Request):
    return request.state.services.exams.papers(course_id)


@router.post("/documents/{document_id}/extract-questions", response_model=PaperOut)
def extract_questions(document_id: str, request: Request):
    return request.state.services.exams.extract(document_id)


@router.post("/courses/{course_id}/questions/search", response_model=list[QuestionOut])
def search_questions(course_id: str, body: QuestionSearch, request: Request):
    return request.state.services.exams.search(course_id, None, body)


@router.get("/courses/{course_id}/questions/{question_id}", response_model=QuestionOut)
def get_question(course_id: str, question_id: str, request: Request):
    return request.state.services.exams.get(course_id, None, question_id)


@router.post("/questions/{question_id}/analyze", response_model=ToolResult)
def analyze_question(question_id: str, body: SearchRequest, request: Request):
    import json

    registry = request.state.services.agent.registry
    registry.exams.validate_scope(body.course_id, body.document_ids)
    context = ToolContext(body)
    args = json.dumps({"question_id": question_id})
    registry.execute("get_question", args, context)
    return registry.execute("analyze_question", args, context)


@router.get("/courses/{course_id}/knowledge-points")
def knowledge_points(course_id: str, request: Request):
    request.state.services.exams.validate_scope(course_id, None)
    with request.state.services.sessions() as session:
        # 只列仍有关联题目的知识点，重解析后无引用的旧标签不进入页面。
        return [
            {"id": point.id, "name": point.name}
            for point in session.scalars(
                select(KnowledgePoint)
                .join(QuestionKnowledgePoint)
                .where(KnowledgePoint.course_id == course_id)
                .distinct()
                .order_by(KnowledgePoint.name)
            )
        ]
