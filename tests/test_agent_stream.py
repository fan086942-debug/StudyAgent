import asyncio
import json
import threading
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api.agent import stream_agent
from app.core.config import Settings
from app.core.errors import AppError
from app.main import create_app
from app.schemas.agent import AgentRequest, AgentTurn
from tests.test_agent import ScriptedPlanner, call


def packets(response):
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def test_stream_reports_real_tools_and_saves_only_final(exam_app):
    app, client, course, _ = exam_app
    response = client.post("/api/agent/stream", json={
        "course_id": course, "question": "A* 以前怎么考过？", "session_id": "a" * 32,
    })
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-store"
    events = packets(response)
    result = events[-1]
    assert result["type"] == "result"
    tools = [event for event in events if event["type"] == "tool"]
    assert [event["status"] for event in tools] == ["running", "ok"]
    assert tools[0]["tool"] == result["data"]["trace"][0]["tool"] == "search_questions"
    assert "arguments" not in tools[1] and "observation" not in tools[1]
    assert events[-2]["stage"] == "validating"
    history = client.get(f"/api/courses/{course}/conversations").json()
    assert len(history) == 1
    assert app.state.connection.active_requests == 0


def test_stream_rejects_invalid_scope_before_headers(exam_app):
    _, client, _, _ = exam_app
    response = client.post("/api/agent/stream", json={"course_id": "missing", "question": "test"})
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")


def test_stream_requires_login(tmp_path):
    app = create_app(Settings(_env_file=None, data_dir=tmp_path, auth_enabled=True))
    with TestClient(app) as client:
        response = client.post("/api/agent/stream", json={"course_id": "private", "question": "test"})
        assert response.status_code == 401
        assert not hasattr(app.state, "connection")


def test_cancel_after_tool_prevents_next_plan_and_memory(exam_app):
    app, client, course, _ = exam_app
    planner = ScriptedPlanner([call("search_questions", {"query": "A*"}), AgentTurn()])
    app.state.agent.planner = planner
    cancelled = threading.Event()

    def progress(event):
        if event["type"] == "tool" and event["status"] == "ok":
            cancelled.set()

    body = AgentRequest(course_id=course, question="test", session_id="b" * 32)
    with pytest.raises(AppError) as error:
        app.state.agent.run(body, progress=progress, cancelled=cancelled.is_set)
    assert error.value.code == "agent_cancelled"
    assert len(planner.messages) == 1
    assert app.state.agent_memory.snapshot(body)["turns"] == []
    assert client.get(f"/api/courses/{course}/conversations").json() == []


def test_disconnected_stream_holds_lease_until_worker_exits(exam_app):
    app, client, course, _ = exam_app
    started, release = threading.Event(), threading.Event()

    class BlockingPlanner:
        def step(self, messages, tools):
            started.set()
            assert release.wait(5)
            return AgentTurn()

    app.state.agent.planner = BlockingPlanner()

    async def check():
        request = SimpleNamespace(state=SimpleNamespace(services=app.state))
        response = await stream_agent(AgentRequest(course_id=course, question="test"), request)
        iterator = response.body_iterator
        await anext(iterator)
        assert await asyncio.to_thread(started.wait, 2)
        assert app.state.connection.active_requests == 1
        await iterator.aclose()
        assert app.state.connection.active_requests == 1
        release.set()
        for _ in range(100):
            if app.state.connection.active_requests == 0:
                break
            await asyncio.sleep(.02)
        assert app.state.connection.active_requests == 0

    try:
        asyncio.run(check())
    finally:
        release.set()
    assert client.get(f"/api/courses/{course}/conversations").json() == []


def test_stream_failure_is_sanitized_and_releases_lease(exam_app, monkeypatch):
    app, client, course, _ = exam_app

    def fail(*args, **kwargs):
        raise RuntimeError("private-secret-provider-response")

    monkeypatch.setattr(app.state.agent, "run", fail)
    response = client.post("/api/agent/stream", json={"course_id": course, "question": "test"})
    assert packets(response)[0]["code"] == "agent_failed"
    assert "private-secret" not in response.text
    assert app.state.connection.active_requests == 0
    assert client.get(f"/api/courses/{course}/conversations").json() == []
