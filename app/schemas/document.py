from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DocumentType = Literal["textbook", "slides", "notes", "exam", "other"]


class CourseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120, pattern=r"\S")
    description: str = Field(default="", max_length=2000)


class CourseOut(CourseCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str
    created_at: str


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    course_id: str
    name: str
    file_type: str
    document_type: str
    status: str
    error: str | None
    warning: str | None
    chunk_count: int
    created_at: str


class TextBlock(BaseModel):
    text: str
    page: int | None = None
    chapter: str | None = None
    section: str | None = None
    block_index: int = 1
    location_type: Literal["pdf_page", "slide", "paragraph", "table"]


class ParsedDocument(BaseModel):
    blocks: list[TextBlock]
    warnings: list[str] = Field(default_factory=list)
