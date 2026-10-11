from fastapi import APIRouter, Depends, Request

from app.core.errors import AppError
from app.schemas.connection import ConnectionInput


def local_access(request: Request):
    loopback = {"127.0.0.1", "localhost", "::1"}
    if (
        not request.client
        or request.client.host not in loopback
        or request.url.hostname not in loopback
    ):
        raise AppError("connection_local_only", "模型连接设置仅允许本机访问", 403)
    origin = request.headers.get("origin")
    if origin and origin != str(request.base_url).rstrip("/"):
        raise AppError("connection_origin", "请从当前学习工作台设置模型连接", 403)
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise AppError("connection_origin", "请从当前学习工作台设置模型连接", 403)


router = APIRouter(
    prefix="/api/connection", tags=["connection"], dependencies=[Depends(local_access)]
)


@router.get("")
def read_connection(request: Request):
    return request.app.state.connection.describe()


@router.put("")
def save_connection(body: ConnectionInput, request: Request):
    return request.app.state.connection.save(body)


@router.post("/test")
def test_connection(body: ConnectionInput, request: Request):
    return request.app.state.connection.test(body)
