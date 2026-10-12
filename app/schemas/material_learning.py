from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.chat import Source
from app.schemas.exam import QuestionOut


class RelationArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    direction: Literal["material_to_exam", "exam_to_material"] = "material_to_exam"
    query: str = Field(default="", max_length=2000)
    material_id: str | None = Field(default=None, min_length=1, max_length=64)
    question_id: str | None = Field(default=None, min_length=1, max_length=64)
    artifact_id: str | None = Field(default=None, min_length=1, max_length=64)
    chunk_ids: list[str] | None = Field(default=None, min_length=1, max_length=100)
    limit: int = Field(default=15, ge=1, le=30)


class RelationRequest(RelationArgs):
    # The two sides have separate scopes: selecting a textbook need not hide all papers.
    document_ids: list[str] | None = Field(default=None, min_length=1, max_length=100)
    exam_document_ids: list[str] | None = Field(default=None, min_length=1, max_length=100)


class MaterialQuestionLink(BaseModel):
    question_id: str
    chunk_ids: list[str]
    concepts: list[str]
    method: Literal["knowledge_label", "text_overlap"]
    score: float


class RelationResult(BaseModel):
    direction: str
    answer: str
    links: list[MaterialQuestionLink]
    sources: list[Source]
    questions: list[QuestionOut]
    warning: str
