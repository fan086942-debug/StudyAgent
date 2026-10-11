from fastapi import APIRouter, Request

from app.schemas.agent import AgentResponse
from app.schemas.chat import SearchRequest

router = APIRouter(prefix="/api", tags=["agent"])


@router.post("/agent", response_model=AgentResponse)
def run_agent(body: SearchRequest, request: Request):
    result = request.app.state.agent.run(body)
    request.app.state.learning.save_conversation(body, "agent", result)
    return result


@router.get("/agent/tools")
def tools(request: Request):
    return request.app.state.agent.registry.schemas()
