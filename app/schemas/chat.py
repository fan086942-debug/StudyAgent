from pydantic import BaseModel, Field

from app.schemas.document import TextBlock


class SearchRequest(BaseModel):
    course_id: str = Field(min_length=1, max_length=64)
    question: str = Field(min_length=1, max_length=2000, pattern=r"\S")
    document_ids: list[str] | None = Field(default=None, min_length=1, max_length=100)


class Source(TextBlock):
    citation_id: str
    chunk_id: str
    course_id: str
    document_id: str
    document_name: str
    document_type: str
    file_type: str
    score: float
    file_url: str


class SearchResponse(BaseModel):
    sources: list[Source]
    retrieval_ms: float


class ChatResponse(BaseModel):
    answer: str
    sources: list[Source]
    mode: str
    insufficient_evidence: bool
    warning: str | None = None
    retrieval_ms: float
    llm_ms: float
    total_ms: float
    usage: dict[str, int] | None = None
