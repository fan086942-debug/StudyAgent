import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.core.static_bundle import BUNDLE_NAME, bundle_text, bundle_version
from app.main import create_app


def test_health(tmp_path):
    with TestClient(create_app(Settings(_env_file=None, data_dir=tmp_path))) as client:
        response = client.get("/health")
        assert response.json()["status"] == "ok"
        assert response.headers["x-request-id"]
        assert client.get("/").status_code == 200
        assert client.get("/static/app.js").status_code == 200


def test_single_css_bundle_is_cacheable_and_complete(tmp_path):
    with TestClient(create_app(Settings(_env_file=None, data_dir=tmp_path))) as client:
        page = client.get("/")
        assert page.headers["cache-control"] == "no-cache"
        assert f"/static/{BUNDLE_NAME}?v={bundle_version()}" in page.text
        assert "/static/app.css" not in page.text

        url = f"/static/{BUNDLE_NAME}?v={bundle_version()}"
        response = client.get(url, headers={"Accept-Encoding": "gzip"})
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/css")
        assert "immutable" in response.headers["cache-control"]
        assert response.headers["content-encoding"] == "gzip"
        assert response.headers["etag"] == f'"{bundle_version()}"'
        assert client.get(url, headers={"If-None-Match": response.headers["etag"]}).status_code == 304
        # An unversioned URL may be requested directly, so it must revalidate.
        assert client.get(f"/static/{BUNDLE_NAME}").headers["cache-control"] == "no-cache"

        css = bundle_text()
        assert "@import" not in css and "@charset" not in css
        assert css.startswith("@layer tokens, base, controls, layout, reader, desk;")
        assert css.count("@layer ") == 7


def test_versioned_js_gets_long_lived_cache(tmp_path):
    with TestClient(create_app(Settings(_env_file=None, data_dir=tmp_path))) as client:
        versioned = client.get("/static/app.js?v=test")
        assert versioned.status_code == 200
        assert "immutable" in versioned.headers["cache-control"]
        unversioned = client.get("/static/app.js")
        assert unversioned.headers["cache-control"] == "public, max-age=3600"


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
