from fastapi import APIRouter, Query, Request
from fastapi.responses import Response

from app.schemas.generation import ArtifactOut, ArtifactSummary, GenerationRequest, StudyPackRequest
from app.services.generation import artifact_markdown
from app.services.material_study import generate_study_pack

router = APIRouter(prefix="/api", tags=["generation"])


@router.post("/generate", response_model=ArtifactOut, status_code=201)
def generate(body: GenerationRequest, request: Request):
    return request.state.services.generation.generate(body)


@router.post("/study", response_model=ArtifactOut, status_code=201)
def study(body: StudyPackRequest, request: Request):
    return generate_study_pack(request.state.services.generation, body)


@router.get("/courses/{course_id}/artifacts", response_model=list[ArtifactSummary])
def artifacts(
    course_id: str,
    request: Request,
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    return request.state.services.generation.list(course_id, limit, offset)


@router.get("/courses/{course_id}/artifacts/{artifact_id}", response_model=ArtifactOut)
def artifact(course_id: str, artifact_id: str, request: Request):
    return request.state.services.generation.get(course_id, artifact_id)


@router.get("/courses/{course_id}/artifacts/{artifact_id}/download")
def download(course_id: str, artifact_id: str, request: Request, include_answers: bool = True):
    result = request.state.services.generation.get(course_id, artifact_id)
    suffix = "answers" if include_answers else "questions"
    return Response(
        artifact_markdown(result, include_answers),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="study-{result.id}-{suffix}.md"'},
    )
