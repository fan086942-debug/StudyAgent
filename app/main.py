import logging
import time
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.courses import router as courses_router
from app.core.config import Settings
from app.core.errors import AppError
from app.db.session import make_database

logger = logging.getLogger("studyagent")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine, sessions = make_database(settings.data_dir)
        app.state.sessions = sessions
        yield
        engine.dispose()

    app = FastAPI(title="StudyAgent", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.include_router(courses_router)

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

    @app.get("/health")
    def health():
        return {"status": "ok", "mode": settings.study_mode, "version": "0.1.0"}

    return app
