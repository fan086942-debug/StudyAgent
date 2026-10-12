from typing import Annotated

from fastapi import APIRouter, Path, Query, Request

from app.schemas.agent import AgentRequest, AgentResponse

router = APIRouter(prefix="/api", tags=["agent"])


@router.post("/agent", response_model=AgentResponse)
def run_agent(body: AgentRequest, request: Request):
    result = request.app.state.agent.run(body)
    request.app.state.learning.save_conversation(body, "agent", result)
    return result


@router.get("/agent/tools")
def tools(request: Request):
    return request.app.state.agent.registry.schemas()


@router.get("/agent/sessions/{session_id}")
def session_context(
    session_id: Annotated[str, Path(pattern=r"^[a-f0-9]{32}$")],
    course_id: Annotated[str, Query(min_length=1, max_length=64)],
    request: Request,
    document_ids: list[str] | None = Query(default=None, min_length=1, max_length=100),
):
    body = AgentRequest(
        course_id=course_id, question="读取会话", document_ids=document_ids, session_id=session_id
    )
    request.app.state.exams.validate_scope(course_id, document_ids)
    return request.app.state.agent_memory.snapshot(body)
