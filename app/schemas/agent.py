from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.llm.base import AnswerBasis, ModelAnswer
from app.schemas.chat import SearchRequest, Source
from app.schemas.exam import QuestionOut
from app.schemas.generation import ArtifactSummary


class FunctionCall(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    arguments: str = Field(max_length=8000)


class AgentRequest(SearchRequest):
    session_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")


class ToolCall(BaseModel):
    id: str = Field(min_length=1, max_length=200)
    type: Literal["function"] = "function"
    function: FunctionCall


class AgentTurn(BaseModel):
    calls: list[ToolCall] = Field(default_factory=list, max_length=12)
    final: ModelAnswer | None = None
    usage: dict[str, int] = Field(default_factory=dict)


class ToolResult(BaseModel):
    answer_basis: AnswerBasis = "materials"
    learning: dict = Field(default_factory=dict)
    plans: list[dict] = Field(default_factory=list)
    artifacts: list[ArtifactSummary] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    questions: list[QuestionOut] = Field(default_factory=list)
    answer: str | None = None
    insufficient_evidence: bool = False
    warning: str | None = None
    usage: dict[str, int] = Field(default_factory=dict)


class ToolTrace(BaseModel):
    step: int
    tool: str
    purpose: str
    arguments: dict
    status: Literal["ok", "error", "cached"]
    observation: dict
    elapsed_ms: float


class AgentResponse(BaseModel):
    answer_basis: AnswerBasis = "materials"
    conversation_id: str | None = None
    session_id: str | None = None
    context_turns: int = 0
    context_reset: bool = False
    learning: dict = Field(default_factory=dict)
    plans: list[dict] = Field(default_factory=list)
    artifacts: list[ArtifactSummary] = Field(default_factory=list)
    answer: str
    sources: list[Source]
    questions: list[QuestionOut]
    trace: list[ToolTrace]
    mode: str
    insufficient_evidence: bool
    finish_reason: str
    warning: str | None = None
    total_ms: float
    usage: dict[str, int]


class KnowledgeArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=2000, pattern=r"\S")


class QuestionArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question_id: str = Field(min_length=1, max_length=64)
