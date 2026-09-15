import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.chat import router as chat_router
from app.api.courses import router as courses_router
from app.api.documents import router as documents_router
from app.core.config import Settings
from app.core.errors import AppError
from app.db.session import make_database
from app.llm.compatible_provider import CompatibleLLM
from app.rag.embedding import APIEmbedding, DemoEmbedding
from app.rag.retriever import Retriever
from app.rag.vector_store import VectorStore
from app.services.ingestion import IngestionService
from app.services.qa import QAService

logger = logging.getLogger("studyagent")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine, sessions = make_database(settings.data_dir)
        app.state.sessions = sessions
        with httpx.Client(timeout=settings.request_timeout, follow_redirects=False) as client:
            app.state.http = client
            embeddings = (
                DemoEmbedding(settings)
                if settings.study_mode == "demo"
                else APIEmbedding(settings, client)
            )
            vectors = VectorStore(settings, embeddings.fingerprint)
            app.state.embeddings, app.state.vectors = embeddings, vectors
            app.state.ingestion = IngestionService(settings, sessions, embeddings, vectors)
            app.state.ingestion.recover_interrupted()
            app.state.ingestion.mark_stale()
            app.state.retriever = Retriever(settings, sessions, embeddings, vectors)
            app.state.qa = QAService(settings, app.state.retriever, CompatibleLLM(settings, client))
            try:
                yield
            finally:
                vectors.client.close()
                engine.dispose()

    app = FastAPI(title="StudyAgent", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.include_router(courses_router)
    app.include_router(documents_router)
    app.include_router(chat_router)
    static = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static), name="static")

    @app.get("/", include_in_schema=False)
    def home():
        return FileResponse(static / "index.html")

    @app.middleware("http")
    async def request_log(request: Request, call_next):
        request.state.request_id = uuid4().hex
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            # 仅记录异常类型，避免外部 API 响应或资料原文泄露。
            logger.error("request=%s error=%s", request.state.request_id, type(exc).__name__)
            response = JSONResponse(
                status_code=500,
                content={
                    "code": "internal_error",
                    "message": "服务内部错误，请查看日志或重试",
                    "request_id": request.state.request_id,
                },
            )
        response.headers["X-Request-ID"] = request.state.request_id
        logger.info(
            "request=%s method=%s path=%s status=%s elapsed_ms=%.1f",
            request.state.request_id,
            request.method,
            request.url.path,
            response.status_code,
            (time.perf_counter() - start) * 1000,
        )
        return response

    @app.exception_handler(AppError)
    async def app_error(request: Request, exc: AppError):
        return JSONResponse(
            status_code=exc.status,
            content={
                "code": exc.code,
                "message": exc.message,
                "request_id": request.state.request_id,
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={
                "code": "validation_error",
                "message": "输入参数不合法，请检查必填项、长度和资料类别",
                "fields": [".".join(str(part) for part in error["loc"]) for error in exc.errors()],
                "request_id": request.state.request_id,
            },
        )

    @app.get("/health")
    def health():
        return {"status": "ok", "mode": settings.study_mode, "version": "0.1.0"}

    return app
