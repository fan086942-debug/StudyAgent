from fastapi import APIRouter, Request

from app.schemas.chat import ChatResponse, SearchRequest, SearchResponse

router = APIRouter(prefix="/api", tags=["RAG"])


@router.post("/search", response_model=SearchResponse)
def search(body: SearchRequest, request: Request):
    return request.app.state.retriever.search(body)


@router.post("/chat", response_model=ChatResponse)
def chat(body: SearchRequest, request: Request):
    return request.app.state.qa.answer(body)
