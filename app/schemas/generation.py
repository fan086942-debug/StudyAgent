from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.chat import Source

Text = Annotated[str, Field(min_length=1, max_length=8000, pattern=r"\S")]
Topic = Annotated[str, Field(min_length=1, max_length=120, pattern=r"\S")]
Citation = Annotated[str, Field(pattern=r"^S[1-9]\d*$")]
PracticeType = Literal["choice", "short_answer", "calculation"]


class GenerationArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topics: list[Topic] = Field(min_length=1, max_length=8)
    question_count: int = Field(default=5, ge=1, le=12)
    question_type: PracticeType = "short_answer"
    difficulty: Literal["easy", "medium", "hard"] = "medium"

    @model_validator(mode="after")
    def unique_topics(self):
        self.topics = list(dict.fromkeys(topic.strip() for topic in self.topics))
        return self


class GenerationRequest(GenerationArgs):
    course_id: str = Field(min_length=1, max_length=64)
    document_ids: list[str] | None = Field(default=None, min_length=1, max_length=100)
    kind: Literal["review", "mock_exam"]


class StudyPackArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_name: str | None = Field(default=None, min_length=1, max_length=255)
    question_count: int | None = Field(default=None, ge=1, le=64)
    question_type: PracticeType = "short_answer"
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    include_questions: bool = True


class StudyPackRequest(StudyPackArgs):
    course_id: str = Field(min_length=1, max_length=64)
    document_ids: list[str] | None = Field(default=None, min_length=1, max_length=100)
    kind: Literal["study_pack"] = "study_pack"


class StudyGenerationTask(BaseModel):
    kind: Literal["review", "mock_exam"]
    topics: list[Topic] = Field(min_length=1, max_length=64)
    question_count: int = Field(default=5, ge=1, le=64)
    question_type: PracticeType = "short_answer"
    difficulty: Literal["easy", "medium", "hard"] = "medium"


class ReviewSection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topic: Topic
    summary: Text
    key_points: list[Text] = Field(min_length=1, max_length=8)
    pitfalls: list[Text] = Field(default_factory=list, max_length=5)
    citation_ids: list[Citation] = Field(min_length=1, max_length=20)


class PracticeQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topic: Topic
    type: PracticeType
    difficulty: Literal["easy", "medium", "hard"]
    stem: Text
    options: list[Text] = Field(default_factory=list, max_length=4)
    answer: Text
    explanation: Text
    citation_ids: list[Citation] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def choice_shape(self):
        if self.type == "choice":
            if len(self.options) != 4 or len(set(self.options)) != 4:
                raise ValueError("选择题必须有四个不同选项")
            if self.answer not in ("A", "B", "C", "D"):
                raise ValueError("选择题答案须为 A/B/C/D")
        elif self.options:
            raise ValueError("非选择题不能含选项")
        return self


class GeneratedContent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Topic
    sections: list[ReviewSection] = Field(default_factory=list, max_length=64)
    questions: list[PracticeQuestion] = Field(default_factory=list, max_length=64)
    insufficient_evidence: bool = False


class ArtifactSummary(BaseModel):
    id: str
    course_id: str
    kind: Literal["review", "mock_exam", "study_pack"]
    title: str
    mode: str
    created_at: str
    warning: str


class ArtifactOut(ArtifactSummary):
    request: Annotated[GenerationRequest | StudyPackRequest, Field(discriminator="kind")]
    content: GeneratedContent
    sources: list[Source]
    usage: dict[str, int]
    total_ms: float
    coverage: dict = Field(default_factory=dict)
