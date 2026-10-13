import asyncio
import json
import logging
import threading
from typing import Annotated

from fastapi import APIRouter, Path, Query, Request
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from app.core.errors import AppError
from app.schemas.agent import AgentRequest, AgentResponse

router = APIRouter(prefix="/api", tags=["agent"])
_active_streams: set[asyncio.Task] = set()
logger = logging.getLogger("studyagent")


@router.post("/agent", response_model=AgentResponse)
def run_agent(body: AgentRequest, request: Request):
    result = request.state.services.agent.run(body)
    request.state.services.learning.save_conversation(body, "agent", result)
    return result


@router.get("/agent/tools")
def tools(request: Request):
    return request.state.services.agent.registry.schemas()


@router.get("/agent/sessions/{session_id}")
def session_context(
    session_id: Annotated[str, Path(pattern=r"^[a-f0-9]{32}$")],
    course_id: Annotated[str, Query(min_length=1, max_length=64)],
    request: Request,
    document_ids: list[str] | None = Query(default=None, min_length=1, max_length=100),
):
    body = AgentRequest(
        course_id=course_id, question="读取会话", document_ids=document_ids, session_id=session_id
    )
    request.state.services.exams.validate_scope(course_id, document_ids)
    return request.state.services.agent_memory.snapshot(body)


@router.post("/agent/stream")
async def stream_agent(body: AgentRequest, request: Request):
    services = request.state.services
    await run_in_threadpool(services.exams.validate_scope, body.course_id, body.document_ids)
    # Middleware releases its lease after headers; the worker owns one until it exits.
    services.connection.enter_request()
    cancelled = threading.Event()
    events = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def emit(event):
        try:
            loop.call_soon_threadsafe(events.put_nowait, event)
        except RuntimeError:
            cancelled.set()

    def work():
        try:
            result = services.agent.run(body, progress=emit, cancelled=cancelled.is_set)
            if not cancelled.is_set():
                services.learning.save_conversation(body, "agent", result)
                emit({"type": "result", "data": result.model_dump(mode="json")})
        except AppError as exc:
            emit({"type": "error", "code": exc.code, "message": exc.message})
        except Exception as exc:
            logger.error("agent streaming task failed error_type=%s", type(exc).__name__)
            emit({"type": "error", "code": "agent_failed", "message": "学习助手处理失败，请重试。"})
        finally:
            services.connection.leave_request()
            emit(None)

    worker = asyncio.create_task(run_in_threadpool(work))
    _active_streams.add(worker)
    worker.add_done_callback(_active_streams.discard)

    async def stream():
        try:
            while True:
                try:
                    event = await asyncio.wait_for(events.get(), timeout=10)
                except TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                if event is None:
                    break
                yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
        finally:
            # The current tool/provider call may finish; no later step or unfinished turn is saved.
            cancelled.set()

    return StreamingResponse(stream(), media_type="text/event-stream", headers={
        "Cache-Control": "no-store", "X-Accel-Buffering": "no"
    })
