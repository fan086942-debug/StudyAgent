from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import create_app
from app.schemas.agent import AgentRequest


def test_delete_saved_agent_record_resets_only_its_session_and_persists(exam_app):
    app, client, course, _ = exam_app
    payload = dict(course_id=course, session_id=uuid4().hex)
    first = client.post("/api/agent", json=dict(payload, question="A*是什么？")).json()
    second = client.post("/api/agent", json=dict(payload, question="它是如何计算的？")).json()
    other_session = dict(payload, session_id=uuid4().hex)
    kept = client.post("/api/agent", json=dict(other_session, question="BFS是什么？")).json()
    assert first["conversation_id"] and second["context_turns"] == 2
    removed = client.delete(f"/api/courses/{course}/conversations/{first['conversation_id']}")
    assert removed.status_code == 200 and removed.json()["context_reset"]
    assert (
        client.get(f"/api/courses/{course}/conversations/{first['conversation_id']}").status_code
        == 404
    )
    assert (
        client.get(f"/api/courses/{course}/conversations/{second['conversation_id']}").status_code
        == 200
    )
    assert app.state.agent_memory.snapshot(AgentRequest(**payload, question="test"))["turns"] == []
    assert (
        len(
            app.state.agent_memory.snapshot(AgentRequest(**other_session, question="test"))["turns"]
        )
        == 1
    )
    assert (
        client.delete(f"/api/courses/{course}/conversations/{first['conversation_id']}").status_code
        == 404
    )
    with TestClient(create_app(app.state.settings)) as restarted:
        assert {
            row["id"] for row in restarted.get(f"/api/courses/{course}/conversations").json()
        } == {second["conversation_id"], kept["conversation_id"]}


def test_delete_chat_and_legacy_records_enforces_course(exam_app):
    app, client, course, _ = exam_app
    record = client.post("/api/chat", json=dict(course_id=course, question="A*是什么？")).json()
    identifier = record["conversation_id"]
    other = client.post("/api/courses", json={"name": "other"}).json()["id"]
    assert client.delete(f"/api/courses/{other}/conversations/{identifier}").status_code == 404
    assert client.get(f"/api/courses/{course}/conversations/{identifier}").status_code == 200
    from app.models import Conversation

    with app.state.sessions() as session:
        session.get(Conversation, identifier).payload = {"answer": "旧版对话"}
        session.commit()
    result = client.delete(f"/api/courses/{course}/conversations/{identifier}")
    assert result.status_code == 200 and not result.json()["context_reset"]
    assert client.get(f"/api/courses/{course}/conversations").json() == []


def test_delete_busy_conversation_keeps_record_and_context(exam_app):
    app, client, course, _ = exam_app
    payload = dict(course_id=course, session_id=uuid4().hex)
    record = client.post("/api/agent", json=dict(payload, question="A*是什么？")).json()
    request = AgentRequest(**payload, question="test")
    url = f"/api/courses/{course}/conversations/{record['conversation_id']}"
    with app.state.agent_memory.turn(request):
        response = client.delete(url)
        assert response.status_code == 409 and response.json()["code"] == "session_busy"
        assert client.get(url).status_code == 200
    assert app.state.agent_memory.snapshot(request)["turns"][0]["id"] == record["conversation_id"]
    assert client.delete(url).status_code == 200
