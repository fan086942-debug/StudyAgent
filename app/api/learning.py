from fastapi import APIRouter, Query, Request

from app.schemas.chat import SearchRequest
from app.schemas.learning import PlanRequest, PracticeRequest, TaskUpdate, WrongUpdate

router = APIRouter(prefix="/api/courses/{course_id}", tags=["learning"])


@router.get("/progress")
def progress(course_id: str, request: Request):
    return request.app.state.learning.progress(
        SearchRequest(course_id=course_id, question="学习进度")
    )


@router.post("/practice", status_code=201)
def practice(course_id: str, body: PracticeRequest, request: Request):
    return request.app.state.learning.record_practice(course_id, body)


@router.get("/wrongbook")
def wrongbook(
    course_id: str,
    request: Request,
    include_mastered: bool = False,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    return request.app.state.learning.wrong_questions(
        SearchRequest(course_id=course_id, question="错题"), include_mastered, limit, offset
    )


@router.patch("/wrongbook/{wrong_id}")
def update_wrong(course_id: str, wrong_id: str, body: WrongUpdate, request: Request):
    return request.app.state.learning.update_wrong(course_id, wrong_id, body.mastered)


@router.post("/plans", status_code=201)
def create_plan(course_id: str, body: PlanRequest, request: Request):
    return request.app.state.learning.create_plan(
        SearchRequest(course_id=course_id, question="复习计划", document_ids=body.document_ids),
        body,
    )


@router.get("/plans")
def plans(
    course_id: str,
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    return request.app.state.learning.plans(course_id, limit, offset)


@router.patch("/plans/{plan_id}/tasks/{task_id}")
def update_task(course_id: str, plan_id: str, task_id: str, body: TaskUpdate, request: Request):
    return request.app.state.learning.update_task(course_id, plan_id, task_id, body.completed)


@router.get("/conversations")
def conversations(
    course_id: str,
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    return request.app.state.learning.conversations(course_id, limit, offset)


@router.get("/conversations/{conversation_id}")
def conversation(course_id: str, conversation_id: str, request: Request):
    return request.app.state.learning.conversation(course_id, conversation_id)
