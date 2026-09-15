from typing import Protocol

from pydantic import BaseModel, Field


class ModelAnswer(BaseModel):
    answer: str = Field(max_length=16000)
    citation_ids: list[str] = Field(default_factory=list, max_length=20)
    insufficient_evidence: bool


class GenerationResult(BaseModel):
    content: ModelAnswer
    usage: dict[str, int] | None = None


class LLMProvider(Protocol):
    def generate(self, question: str, evidence: list[dict]) -> GenerationResult: ...
