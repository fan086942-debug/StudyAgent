from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select

from app.core.config import Settings
from app.db.session import make_database
from app.main import create_app
from app.models import Course
from app.services.auth import User


def test_empty_cloud_setup_creates_private_workspace_without_server_key(tmp_path):
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path,
        auth_enabled=True,
        auth_allow_remote_setup=True,
        llm_api_key=SecretStr("server-private-key"),
        llm_model="server-model",
    )
    app = create_app(settings)
    with TestClient(app, client=("198.51.100.1", 123), base_url="http://public.example") as client:
        assert client.get("/api/auth/me").json()["setup_local_only"] is False
        response = client.post(
            "/api/auth/register", json={"username": "cloud_user", "password": "123456"}
        )
        assert response.status_code == 201, response.text
        with app.state.auth.sessions() as db:
            user = db.scalar(select(User))
            assert not user.legacy_workspace
        connection = client.get("/api/connection").json()
        assert connection["mode"] == "demo" and not connection["has_api_key"]


def test_cloud_setup_cannot_claim_existing_legacy_data(tmp_path):
    engine, sessions = make_database(tmp_path)
    with sessions() as db:
        db.add(Course(name="existing private course"))
        db.commit()
    engine.dispose()
    app = create_app(
        Settings(_env_file=None, data_dir=tmp_path, auth_enabled=True, auth_allow_remote_setup=True)
    )
    with TestClient(app, client=("198.51.100.1", 123), base_url="http://public.example") as client:
        assert client.get("/api/auth/me").json()["setup_local_only"]
        assert (
            client.post(
                "/api/auth/register", json={"username": "cloud_user", "password": "123456"}
            ).status_code
            == 403
        )


def test_render_proxy_https_origin_and_secure_cookie(monkeypatch, tmp_path):
    monkeypatch.setenv("RENDER", "true")
    settings = Settings(_env_file=None, data_dir=tmp_path, auth_enabled=True)
    assert settings.auth_cookie_secure and settings.auth_allow_remote_setup
    app = create_app(settings)
    headers = {
        "X-Forwarded-Proto": "https",
        "X-Forwarded-For": "198.51.100.1",
        "Origin": "https://public.example",
    }
    with TestClient(app, base_url="http://public.example") as client:
        response = client.post(
            "/api/auth/register",
            json={"username": "cloud_user", "password": "123456"},
            headers=headers,
        )
        assert response.status_code == 201, response.text
        assert "Secure" in response.headers["set-cookie"]
        assert client.get("https://public.example/api/courses").status_code == 200
        headers["Origin"] = "https://other.example"
        assert (
            client.post(
                "/api/auth/login",
                json={"username": "cloud_user", "password": "123456"},
                headers=headers,
            ).status_code
            == 403
        )
