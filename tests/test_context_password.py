import json
import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import Settings
from app.main import create_app
from app.models import AgentContext
from app.services.agent_memory import AgentMemory
from tests.test_agent_memory import material


@pytest.mark.parametrize("password", ["123456", "密碼测试六字符", "a" * 1024 + "尾"])
def test_password_six_or_long_roundtrip_without_truncation(tmp_path, password):
    settings = Settings(_env_file=None, data_dir=tmp_path, auth_enabled=True)
    with TestClient(create_app(settings)) as client:
        schema = client.get("/openapi.json").json()["components"]["schemas"]["Credentials"][
            "properties"
        ]["password"]
        assert schema["minLength"] == 6 and "maxLength" not in schema
        assert (
            client.post(
                "/api/auth/register", json={"username": "length_test", "password": "12345"}
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/auth/register", json={"username": "length_test", "password": password}
            ).status_code
            == 201
        )
        client.post("/api/auth/logout")
        assert (
            client.post(
                "/api/auth/login", json={"username": "length_test", "password": password[:-1] + "x"}
            ).status_code
            == 401
        )
        assert (
            client.post(
                "/api/auth/login", json={"username": "length_test", "password": password}
            ).status_code
            == 200
        )


def test_context_survives_application_restart_and_continues_generation(exam_app):
    app, client, course, _ = exam_app
    document = material(client, course)
    payload = dict(course_id=course, document_ids=[document], session_id=uuid4().hex)
    first = client.post("/api/agent", json=dict(payload, question="根据层次聚类出两道题目")).json()
    assert first["context_turns"] == 1 and first["artifacts"]
    with TestClient(create_app(app.state.settings)) as restarted:
        snapshot = restarted.get(
            f"/api/agent/sessions/{payload['session_id']}",
            params={"course_id": course, "document_ids": document},
        ).json()
        assert not snapshot["context_reset"] and len(snapshot["turns"]) == 1
        assert len(snapshot["turns"][0]["generated_questions"]) == 2
        second = restarted.post("/api/agent", json=dict(payload, question="再来两道题")).json()
        assert second["context_turns"] == 2 and second["artifacts"]
        assert second["trace"][0]["arguments"]["topics"] == ["层次聚类"]
        assert not second["context_reset"]


def test_deleting_restored_conversation_clears_durable_context(exam_app):
    app, client, course, _ = exam_app
    identifier = uuid4().hex
    result = client.post(
        "/api/agent", json={"course_id": course, "session_id": identifier, "question": "A*是什么？"}
    ).json()
    with TestClient(create_app(app.state.settings)) as restarted:
        response = restarted.delete(
            f"/api/courses/{course}/conversations/{result['conversation_id']}"
        )
        assert response.status_code == 200 and response.json()["context_reset"]
    with TestClient(create_app(app.state.settings)) as twice:
        snapshot = twice.get(
            f"/api/agent/sessions/{identifier}", params={"course_id": course}
        ).json()
        assert snapshot["turns"] == []


def test_durable_ttl_capacity_and_scope_fingerprint(exam_app):
    app, client, course, document = exam_app
    identifier = uuid4().hex
    client.post(
        "/api/agent", json={"course_id": course, "session_id": identifier, "question": "A*是什么？"}
    )
    with app.state.sessions() as db:
        db.get(AgentContext, identifier).updated_at = time.time() - AgentMemory.ttl - 1
        db.commit()
    with TestClient(create_app(app.state.settings)) as restarted:
        snapshot = restarted.get(
            f"/api/agent/sessions/{identifier}", params={"course_id": course}
        ).json()
        assert snapshot["turns"] == [] and snapshot["context_reset"]
    app.state.agent_memory.max_sessions = 2
    app.state.agent_memory.entries.clear()
    for _ in range(4):
        client.get(f"/api/agent/sessions/{uuid4().hex}", params={"course_id": course})
    with app.state.sessions() as db:
        assert len(list(db.scalars(select(AgentContext)))) <= 2
    fresh_id = uuid4().hex
    client.post(
        "/api/agent", json={"course_id": course, "session_id": fresh_id, "question": "A*是什么？"}
    )
    assert client.delete(f"/api/documents/{document}").status_code == 200
    with TestClient(create_app(app.state.settings)) as restarted:
        snapshot = restarted.get(
            f"/api/agent/sessions/{fresh_id}", params={"course_id": course}
        ).json()
        assert snapshot["turns"] == [] and snapshot["context_reset"]


def test_durable_context_isolated_between_accounts(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path, auth_enabled=True)
    identifier = uuid4().hex
    with TestClient(create_app(settings)) as client:
        client.post("/api/auth/register", json={"username": "owner_one", "password": "123456"})
        course = client.post("/api/courses", json={"name": "private"}).json()["id"]
        client.post(
            "/api/agent",
            json={"course_id": course, "session_id": identifier, "question": "PRIVATE_CONTEXT"},
        )
        token = client.cookies.get("study_session")
        client.cookies.clear()
        client.post("/api/auth/register", json={"username": "owner_two", "password": "123456"})
        assert (
            client.get(
                f"/api/agent/sessions/{identifier}", params={"course_id": course}
            ).status_code
            == 404
        )
        other_course = client.post("/api/courses", json={"name": "other"}).json()["id"]
        assert (
            client.get(
                f"/api/agent/sessions/{identifier}", params={"course_id": other_course}
            ).json()["turns"]
            == []
        )
    with TestClient(create_app(settings)) as restarted:
        restarted.cookies.set("study_session", token)
        response = restarted.get(f"/api/agent/sessions/{identifier}", params={"course_id": course})
        assert response.status_code == 200 and "PRIVATE_CONTEXT" in json.dumps(response.json())
