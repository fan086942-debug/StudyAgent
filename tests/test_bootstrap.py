import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.main import create_app


def test_health(tmp_path):
    with TestClient(create_app(Settings(_env_file=None, data_dir=tmp_path))) as client:
        response = client.get("/health")
        assert response.json()["status"] == "ok"
        assert response.headers["x-request-id"]
        assert client.get("/").status_code == 200
        assert client.get("/static/app.js").status_code == 200


def test_invalid_config():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, chunk_overlap=800)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, study_mode="api")


def test_default_workspace_runs_without_login(tmp_path, monkeypatch):
    monkeypatch.delenv("AUTH_ENABLED", raising=False)
    config = Settings(_env_file=None, data_dir=tmp_path)
    assert config.auth_enabled is False
    with TestClient(create_app(config), base_url="http://127.0.0.1",
                    client=("127.0.0.1", 12345)) as client:
        assert client.get("/api/auth/me").json() == {"enabled": False, "user": None}
        course = client.post("/api/courses", json={"name": "核心学习流程"})
        assert course.status_code == 201
        assert client.get("/api/courses").json()[0]["name"] == "核心学习流程"


def test_real_model_required_without_offline_fallback(tmp_path, monkeypatch):
    monkeypatch.delenv("REQUIRE_REAL_MODEL", raising=False)
    config = Settings(_env_file=None, data_dir=tmp_path, auth_enabled=False)
    assert config.require_real_model is True
    with TestClient(create_app(config), base_url="http://127.0.0.1",
                    client=("127.0.0.1", 12345)) as client:
        profile = client.get("/api/connection").json()
        assert profile["mode"] == "api" and profile["configured"] is False
        course = client.post("/api/courses", json={"name": "API required"}).json()["id"]
        for path in ["/api/agent", "/api/chat", "/api/generate", "/api/study"]:
            response = client.post(path, json={"course_id": course, "question": "问题"})
            assert response.status_code == 422
            assert response.json()["code"] == "connection_required"
        response = client.put("/api/connection", json={"mode": "demo"})
        assert response.status_code == 422 and response.json()["code"] == "offline_disabled"
