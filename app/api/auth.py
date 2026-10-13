from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field, field_validator

from app.core.errors import AppError
from app.services.auth import COOKIE, public_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[a-zA-Z0-9_-]+$")
    password: str = Field(min_length=10, max_length=128)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value):
        return value.lower()


def auth_service(request):
    if not request.app.state.settings.auth_enabled:
        raise AppError("auth_disabled", "当前为本地免登录模式", 409)
    return request.app.state.auth


def set_session(request, response, user):
    service = auth_service(request)
    token = service.create_session(user, request.cookies.get(COOKIE))
    response.set_cookie(
        COOKIE, token, max_age=service.settings.auth_session_hours * 3600,
        httponly=True, secure=service.settings.auth_cookie_secure, samesite="strict", path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    return {"user": public_user(user)}


@router.get("/me")
def me(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    if not request.app.state.settings.auth_enabled:
        return {"enabled": False, "user": None}
    service = auth_service(request)
    user = service.authenticate(request.cookies.get(COOKIE))
    setup = not service.has_users()
    return {
        "enabled": True, "user": public_user(user) if user else None,
        "setup_required": setup,
        "registration_enabled": setup or service.settings.auth_registration_enabled,
    }


@router.post("/register", status_code=201)
def register(body: Credentials, request: Request, response: Response):
    service = auth_service(request)
    service.throttle(request.client.host if request.client else "unknown")
    loopback = {"127.0.0.1", "::1", "localhost", "testclient"}
    local = bool(request.client and request.client.host in loopback
                 and request.url.hostname in loopback | {"testserver"})
    user = service.register(body.username, body.password, local)
    return set_session(request, response, user)


@router.post("/login")
def login(body: Credentials, request: Request, response: Response):
    service = auth_service(request)
    service.throttle(request.client.host if request.client else "unknown")
    return set_session(request, response, service.login(body.username, body.password))


@router.post("/logout")
def logout(request: Request, response: Response):
    auth_service(request).logout(request.cookies.get(COOKIE))
    response.delete_cookie(COOKIE, path="/", samesite="strict")
    response.headers["Cache-Control"] = "no-store"
    return {"status": "ok"}
