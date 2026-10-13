from fastapi import APIRouter, Request

from app.schemas.chat import ChatResponse, SearchRequest, SearchResponse

router = APIRouter(prefix="/api", tags=["RAG"])


@router.post("/search", response_model=SearchResponse)
def search(body: SearchRequest, request: Request):
    return request.state.services.retriever.search(body)


@router.post("/chat", response_model=ChatResponse)
def chat(body: SearchRequest, request: Request):
    result = request.state.services.qa.answer(body)
    request.state.services.learning.save_conversation(body, "chat", result)
    return result
