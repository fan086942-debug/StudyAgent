import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.api.agent import router as agent_router
from app.api.auth import router as auth_router
from app.api.chat import router as chat_router
from app.api.connection import router as connection_router
from app.api.courses import router as courses_router
from app.api.documents import router as documents_router
from app.api.exams import router as exams_router
from app.api.exports import router as exports_router
from app.api.generation import router as generation_router
from app.api.learning import router as learning_router
from app.api.material_learning import router as material_learning_router
from app.core.config import Settings
from app.core.errors import AppError
from app.core.http import LazyHTTPClient
from app.services.auth import COOKIE, AuthService
from app.services.workspaces import Workspaces, initialize_workspace

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
        started = time.perf_counter()
        with LazyHTTPClient(settings.request_timeout) as client:
            if settings.auth_enabled:
                app.state.auth = AuthService(settings)
                app.state.workspaces = Workspaces(settings, client)
            else:
                initialize_workspace(app.state, settings, client)
                app.state.workspaces = Workspaces(settings, client, app.state)
                app.state.workspaces.states["legacy"] = app.state
            app.state.startup_ms = round((time.perf_counter() - started) * 1000, 1)
            logger.info("startup ready elapsed_ms=%.1f vector_index=lazy", app.state.startup_ms)
            try:
                yield
            finally:
                app.state.workspaces.close()
                if settings.auth_enabled:
                    app.state.auth.engine.dispose()

    app = FastAPI(title="StudyAgent", version="0.4.0", lifespan=lifespan)
    app.state.settings = settings
    app.include_router(auth_router)
    app.include_router(courses_router)
    app.include_router(documents_router)
    app.include_router(chat_router)
    app.include_router(exams_router)
    app.include_router(agent_router)
    app.include_router(generation_router)
    app.include_router(exports_router)
    app.include_router(learning_router)
    app.include_router(material_learning_router)
    app.include_router(connection_router)
    static = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static), name="static")

    @app.get("/", include_in_schema=False)
    def home():
        return FileResponse(static / "index.html")

    @app.middleware("http")
    async def request_log(request: Request, call_next):
        request.state.request_id = uuid4().hex
        start = time.perf_counter()
        connection = None
        entered = False
        try:
            path = request.url.path
            is_api = path.startswith("/api/")
            is_auth = path.startswith("/api/auth/")
            if settings.auth_enabled and is_api and request.method not in {"GET", "HEAD", "OPTIONS"}:
                origin = request.headers.get("origin")
                if ((origin and origin != str(request.base_url).rstrip("/"))
                        or request.headers.get("sec-fetch-site") == "cross-site"):
                    raise AppError("origin_forbidden", "请从当前站点提交操作", 403)
            request.state.services = app.state
            if settings.auth_enabled and is_api and not is_auth:
                user = await run_in_threadpool(
                    app.state.auth.authenticate, request.cookies.get(COOKIE)
                )
                if user is None:
                    raise AppError("login_required", "请先登录后继续", 401)
                request.state.user = user
                request.state.services = await run_in_threadpool(app.state.workspaces.get, user)
            connection = getattr(request.state.services, "connection", None)
            if connection and is_api and not is_auth and not path.startswith("/api/connection"):
                connection.enter_request(require_model=(
                    path in {"/api/agent", "/api/agent/stream", "/api/chat", "/api/generate", "/api/study"}
                    or path.endswith(("/analyze", "/extract-questions"))
                ))
                entered = True
            response = await call_next(request)
        except AppError as exc:
            response = JSONResponse(
                status_code=exc.status,
                content={
                    "code": exc.code,
                    "message": exc.message,
                    "usage": exc.usage,
                    "request_id": request.state.request_id,
                },
            )
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
        finally:
            if entered:
                connection.leave_request()
        response.headers["X-Request-ID"] = request.state.request_id
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
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
                "usage": exc.usage,
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
        return {
            "status": "ok",
            "mode": app.state.settings.study_mode,
            "version": "0.4.0",
            "build": "20261021-local-word-exams",
            "commit": os.environ.get("RENDER_GIT_COMMIT", "local"),
            "max_upload_mb": settings.max_upload_mb,
            "ocr_enabled": settings.ocr_enabled,
            "auth_enabled": settings.auth_enabled,
            "startup_ms": app.state.startup_ms,
        }

    if os.environ.get("RENDER") == "true":
        # Render terminates HTTPS at its ingress; normalize scheme before origin validation.
        app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")
    return app
