from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PracticeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reference_type: Literal["question", "artifact", "wrongbook"]
    reference_id: str = Field(min_length=1, max_length=64)
    question_index: int = Field(default=0, ge=0, le=11)
    answer: str = Field(default="", max_length=6000)
    outcome: Literal["wrong", "correct"]
    note: str = Field(default="", max_length=1000)


class WrongUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mastered: bool


class PlanArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topics: list[str] = Field(default_factory=list, max_length=8)
    days: int = Field(default=7, ge=1, le=30)
    daily_minutes: int = Field(default=30, ge=10, le=180)

    @field_validator("topics")
    @classmethod
    def clean_topics(cls, values):
        result = list(dict.fromkeys(value.strip() for value in values))
        if any(not value or len(value) > 120 for value in result):
            raise ValueError("主题应为 1–120 个字符")
        return result


class PlanRequest(PlanArgs):
    document_ids: list[str] | None = Field(default=None, min_length=1, max_length=100)


class TaskUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    completed: bool


class LearningArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WrongListArgs(LearningArgs):
    limit: int = Field(default=20, ge=1, le=50)
