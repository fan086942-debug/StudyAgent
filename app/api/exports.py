from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import Response

from app.core.errors import AppError

router = APIRouter(prefix="/api", tags=["Word export"])
MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def word_response(content, identifier, kind):
    return Response(content, media_type=MIME, headers={
        "Content-Disposition": f'attachment; filename="study-{identifier}-{kind}.docx"',
        "Cache-Control": "no-store",
    })


@router.get("/courses/{course_id}/artifacts/{artifact_id}/word")
def export_artifact(course_id: str, artifact_id: str, request: Request,
                    kind: Literal["qa", "knowledge"] = "qa"):
    # python-docx is only needed when a download is requested; import lazily so
    # it does not slow every cold process start.
    from app.services.word_export import artifact_word

    artifact = request.state.services.generation.get(course_id, artifact_id)
    return word_response(artifact_word(artifact, kind), artifact_id, kind)


@router.get("/courses/{course_id}/conversations/{conversation_id}/word")
def export_conversation(course_id: str, conversation_id: str, request: Request,
                        kind: Literal["qa", "knowledge"] = "qa"):
    from app.services.word_export import artifact_word, conversation_word

    services = request.state.services
    record = services.learning.conversation(course_id, conversation_id)
    if record["result"].get("insufficient_evidence", False):
        raise AppError("export_no_result", "本次尚未完成解答，请完成后再整理", 409)
    artifacts = record["result"].get("artifacts", [])
    if len(artifacts) == 1:
        artifact = services.generation.get(course_id, artifacts[0]["id"])
        return word_response(artifact_word(artifact, kind), conversation_id, kind)
    return word_response(conversation_word(record, kind), conversation_id, kind)
