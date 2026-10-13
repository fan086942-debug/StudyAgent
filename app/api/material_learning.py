from fastapi import APIRouter, Query, Request

from app.schemas.material_learning import RelationRequest, RelationResult

router = APIRouter(prefix="/api/courses/{course_id}", tags=["material-learning"])


@router.post("/material-question-links", response_model=RelationResult)
def material_question_links(course_id: str, body: RelationRequest, request: Request):
    return request.state.services.material_learning.relations(course_id, body)


@router.get("/material-knowledge")
def material_knowledge(
    course_id: str, request: Request, document_id: str | None = Query(default=None, max_length=64)
):
    return request.state.services.material_learning.knowledge(course_id, document_id)
