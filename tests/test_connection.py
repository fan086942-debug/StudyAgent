import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.agent.planner import APIPlanner, DemoPlanner
from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def connected_app(tmp_path):
    app = create_app(Settings(_env_file=None, data_dir=tmp_path))
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 12345)) as client:
        yield app, client


def profile(**updates):
    return dict(
        mode="api",
        base_url="https://model.example/v1",
        model="test-model",
        api_key="test-private-key",
        **updates,
    )


def test_switch_persist_and_retain_index(connected_app, tmp_path):
    app, client = connected_app
    fingerprint = app.state.embeddings.fingerprint
    embedding, vectors = app.state.embeddings, app.state.vectors
    response = client.put("/api/connection", json=profile())
    assert response.status_code == 200
    assert "test-private-key" not in response.text
    assert response.json()["has_api_key"] is True
    assert client.get("/health").json()["mode"] == "api"
    assert isinstance(app.state.agent.planner, APIPlanner)
    assert app.state.embeddings is embedding and app.state.vectors is vectors
    for service in [app.state.qa, app.state.exams, app.state.generation, app.state.agent]:
        assert service.settings.study_mode == "api"
        assert service.settings.llm_model == "test-model"
    assert app.state.ingestion.exams is app.state.exams
    assert "test-private-key" not in client.get("/api/connection").text
    assert (
        json.loads((tmp_path / "model-connection.json").read_text())["api_key"]
        == "test-private-key"
    )
    with TestClient(
        create_app(Settings(_env_file=None, data_dir=tmp_path)),
        base_url="http://127.0.0.1",
        client=("127.0.0.1", 12346),
    ) as restarted:
        assert restarted.get("/health").json()["mode"] == "api"
        assert restarted.app.state.embeddings.fingerprint == fingerprint
        response = restarted.put(
            "/api/connection", json={**profile(), "mode": "demo", "api_key": ""}
        )
        assert response.status_code == 200
        assert isinstance(restarted.app.state.agent.planner, DemoPlanner)
        assert restarted.get("/api/connection").json()["has_api_key"]


@pytest.mark.parametrize("base_url", ["https://model.example/v1", "https://api.deepseek.com"])
def test_connection_and_agent_use_model_http(connected_app, base_url):
    app, client = connected_app
    calls = []

    def provider(request):
        assert str(request.url) == base_url + "/chat/completions"
        assert request.headers["authorization"] == "Bearer test-private-key"
        body = json.loads(request.content)
        assert body["model"] == "test-model"
        if base_url == "https://api.deepseek.com":
            assert body["thinking"] == {"type": "disabled"}
        else:
            assert "thinking" not in body
        calls.append(body)
        if body.get("tool_choice") != "auto":
            message = {
                "tool_calls": [
                    {"function": {"name": "connection_check", "arguments": '{"ok":true}'}}
                ]
            }
        elif not any(row["role"] == "tool" for row in body["messages"]):
            message = {
                "tool_calls": [
                    {
                        "id": "call-progress",
                        "type": "function",
                        "function": {"name": "get_learning_progress", "arguments": "{}"},
                    }
                ]
            }
        else:
            message = {
                "content": json.dumps(
                    {"answer": "已查看学习记录", "citation_ids": [], "insufficient_evidence": False}
                )
            }
        return httpx.Response(200, json={"choices": [{"message": message}]})

    with httpx.Client(transport=httpx.MockTransport(provider)) as http:
        app.state.http = http
        connection = {**profile(), "base_url": base_url}
        assert client.post("/api/connection/test", json=connection).json()["status"] == "ok"
        assert client.get("/health").json()["mode"] == "demo"
        assert not app.state.connection.path.exists()
        assert client.put("/api/connection", json=connection).status_code == 200
        course = client.post("/api/courses", json={"name": "API 连接验收"}).json()
        result = client.post(
            "/api/agent", json={"course_id": course["id"], "question": "查看学习进度"}
        )
        assert result.status_code == 200
        assert result.json()["mode"] == "api"
        assert result.json()["trace"][0]["tool"] == "get_learning_progress"
        assert len(calls) == 3


def test_key_reuse_and_endpoint_change(connected_app):
    app, client = connected_app
    assert client.put("/api/connection", json=profile()).status_code == 200
    assert (
        client.put(
            "/api/connection", json={**profile(), "api_key": "", "model": "new-model"}
        ).status_code
        == 200
    )
    assert app.state.settings.llm_api_key.get_secret_value() == "test-private-key"
    response = client.put(
        "/api/connection", json={**profile(), "api_key": "", "base_url": "https://other.example/v1"}
    )
    assert response.status_code == 422
    assert response.json()["code"] == "connection_key_required"
    assert app.state.settings.llm_model == "new-model"


def test_invalid_config_busy_and_atomic_failure(connected_app, monkeypatch):
    app, client = connected_app
    assert client.put("/api/connection", json={**profile(), "model": ""}).status_code == 422
    assert (
        client.put("/api/connection", json={**profile(), "base_url": "file:///secret"}).status_code
        == 422
    )
    app.state.connection.enter_request()
    try:
        assert client.put("/api/connection", json=profile()).status_code == 409
    finally:
        app.state.connection.leave_request()
    assert client.get("/api/courses").status_code == 200
    assert app.state.connection.active_requests == 0

    def fail_save(*args):
        raise OSError("disk unavailable")

    monkeypatch.setattr("app.services.connection.os.replace", fail_save)
    assert client.put("/api/connection", json=profile()).status_code == 500
    assert client.get("/health").json()["mode"] == "demo"
    assert not app.state.connection.path.exists()
    assert not list(app.state.connection.path.parent.glob(".model-connection-*.tmp"))


def test_local_and_same_origin_only(connected_app):
    _, client = connected_app
    read_only = client.get("/api/connection", headers={"host": "attacker.example"})
    assert read_only.status_code == 200 and read_only.json()["editable"] is False
    assert "api_key" not in read_only.json()
    assert (
        client.put(
            "/api/connection", json=profile(), headers={"origin": "https://other.example"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/connection/test", json=profile(), headers={"sec-fetch-site": "cross-site"}
        ).status_code
        == 403
    )


def test_provider_error_and_tools_unsupported(connected_app):
    app, client = connected_app
    for response, code in [
        (httpx.Response(401, json={"secret": "must-not-leak"}), "provider_http_error"),
        (
            httpx.Response(200, json={"choices": [{"message": {"content": "hello"}}]}),
            "connection_tools_unsupported",
        ),
    ]:
        with httpx.Client(transport=httpx.MockTransport(lambda request: response)) as http:
            app.state.http = http
            result = client.post("/api/connection/test", json=profile())
            assert result.status_code == 502
            assert result.json()["code"] == code
            assert "must-not-leak" not in result.text
    assert client.get("/health").json()["mode"] == "demo"
