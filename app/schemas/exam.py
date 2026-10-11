from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

QuestionType = Literal[
    "choice", "true_false", "fill_blank", "short_answer", "calculation", "essay", "unknown"
]
Difficulty = Literal["easy", "medium", "hard", "unknown"]


class ExtractedQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    number: str = Field(min_length=1, max_length=64)
    type: QuestionType = "unknown"
    source_text: str = Field(min_length=1, max_length=16000)
    options: list[str] = Field(default_factory=list, max_length=20)
    score: float | None = Field(default=None, ge=0, le=1000, allow_inf_nan=False)
    knowledge_points: list[str] = Field(default_factory=list, max_length=12)
    difficulty: Difficulty = "unknown"


class ExtractionBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    questions: list[ExtractedQuestion] = Field(max_length=100)


class QuestionOut(BaseModel):
    id: str
    paper_id: str
    document_id: str
    paper_name: str
    file_type: str
    number: str
    type: QuestionType
    content: str
    options: list[str]
    score: float | None
    difficulty: Difficulty
    knowledge_points: list[str]
    locations: list[dict]
    file_url: str
    extraction_method: str


class PaperOut(BaseModel):
    id: str
    document_id: str
    name: str
    status: str
    error: str | None
    warning: str | None
    question_count: int
    extraction_method: str


class QuestionSearch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(default="", max_length=2000)
    paper_id: str | None = Field(default=None, max_length=64)
    paper_name: str | None = Field(default=None, max_length=255)
    number: str | None = Field(default=None, max_length=64)
    question_type: QuestionType | None = None
    knowledge_point: str | None = Field(default=None, max_length=120)
    limit: int = Field(default=10, ge=1, le=30)
