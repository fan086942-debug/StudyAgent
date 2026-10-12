import json
from uuid import uuid4

import pytest

from app.core.errors import AppError
from app.llm.base import ModelAnswer
from app.schemas.agent import AgentRequest, AgentTurn
from app.services.agent_memory import AgentMemory
from tests.test_agent import ScriptedPlanner, call
from tests.test_exams import exam_bytes


def material(client, course):
    result = client.post(
        f"/api/courses/{course}/documents",
        files={
            "file": (
                "层次聚类.docx",
                exam_bytes(
                    "凝聚层次聚类从单点簇开始。层次聚类合并最近的簇。\n层次聚类的单链接取最小距离。层次聚类的完全链接取最大距离。"
                ),
            )
        },
        data={"document_type": "textbook"},
    )
    assert result.status_code == 201
    return result.json()["id"]


def test_topic_followup_refresh_and_session_isolation(exam_app):
    app, client, course, _ = exam_app
    document = material(client, course)
    identifier = uuid4().hex
    payload = dict(course_id=course, document_ids=[document], session_id=identifier)
    first = client.post("/api/agent", json=dict(payload, question="根据层次聚类出两道题目")).json()
    assert first["artifacts"] and first["context_turns"] == 1
    second = client.post("/api/agent", json=dict(payload, question="再来两道题")).json()
    assert second["artifacts"] and second["context_turns"] == 2
    assert second["trace"][0]["arguments"]["topics"] == ["层次聚类"]
    assert second["trace"][0]["arguments"]["question_count"] == 2
    first_artifact = client.get(
        f"/api/courses/{course}/artifacts/{first['artifacts'][0]['id']}"
    ).json()
    second_artifact = client.get(
        f"/api/courses/{course}/artifacts/{second['artifacts'][0]['id']}"
    ).json()
    assert {q["stem"] for q in first_artifact["content"]["questions"]}.isdisjoint(
        q["stem"] for q in second_artifact["content"]["questions"]
    )
    assert (
        client.get("/api/agent/sessions/invalid", params=dict(course_id=course)).status_code == 422
    )
    snapshot = client.get(
        f"/api/agent/sessions/{identifier}", params=dict(course_id=course, document_ids=document)
    ).json()
    assert len(snapshot["turns"]) == 2 and len(snapshot["turns"][0]["generated_questions"]) == 2
    fresh = client.post(
        "/api/agent", json=dict(payload, session_id=uuid4().hex, question="再出两道题")
    ).json()
    assert not fresh["artifacts"] and "知识点" in fresh["answer"]
    assert (
        client.post(
            "/api/agent", json=dict(course_id=course, session_id=identifier, question="它是什么")
        ).status_code
        == 409
    )
    other = client.post("/api/courses", json={"name": "other"}).json()["id"]
    assert (
        client.get(f"/api/agent/sessions/{identifier}", params=dict(course_id=other)).status_code
        == 409
    )
    assert (
        client.post(
            "/api/agent", json=dict(payload, question="再来两道题", session_id="invalid")
        ).status_code
        == 422
    )


def test_planner_receives_generated_questions_for_followup(exam_app):
    app, client, course, _ = exam_app
    document = material(client, course)
    payload = dict(course_id=course, document_ids=[document], session_id=uuid4().hex)
    first = client.post("/api/agent", json=dict(payload, question="根据层次聚类出两道题目")).json()
    assert first["artifacts"]
    planner = ScriptedPlanner(
        [
            call("search_knowledge", {"query": "层次聚类"}),
            AgentTurn(
                final=ModelAnswer(
                    answer="层次聚类合并距离最近的簇 [S1]",
                    citation_ids=["S1"],
                    insufficient_evidence=False,
                )
            ),
        ]
    )
    app.state.agent.planner = planner
    app.state.agent.settings.study_mode = "api"
    result = client.post(
        "/api/agent", json=dict(payload, question="解释第二题，为什么这样做？")
    ).json()
    assert result["finish_reason"] == "completed" and result["context_turns"] == 2
    messages = planner.messages[0]
    assert messages[-1]["content"] == "解释第二题，为什么这样做？"
    old = json.loads(messages[2]["content"])
    assert old["question"] == "根据层次聚类出两道题目"
    assert len(old["generated_questions"]) == 2 and old["generated_questions"][1]["answer"]
    assert result["sources"][0]["document_id"] == document
    isolated = ScriptedPlanner(
        [
            AgentTurn(
                final=ModelAnswer(
                    answer="请说明哪道题", citation_ids=[], insufficient_evidence=True
                )
            )
        ]
    )
    app.state.agent.planner = isolated
    client.post("/api/agent", json=dict(payload, session_id=uuid4().hex, question="解释第二题"))
    assert len(isolated.messages[0]) == 2


def test_memory_invalidates_after_material_change_and_expires(exam_app):
    app, client, course, _ = exam_app
    document = material(client, course)
    identifier = uuid4().hex
    payload = dict(course_id=course, session_id=identifier)
    first = client.post("/api/agent", json=dict(payload, question="根据层次聚类出两道题目")).json()
    assert first["artifacts"]
    assert client.delete(f"/api/documents/{document}").status_code == 200
    empty = client.get(f"/api/agent/sessions/{identifier}", params={"course_id": course}).json()
    assert empty["turns"] == [] and empty["context_reset"]
    request = AgentRequest(**payload, question="test")
    entry = app.state.agent_memory.entries[identifier]
    entry.updated -= AgentMemory.ttl + 1
    assert app.state.agent_memory.snapshot(request)["context_reset"]
    with app.state.agent_memory.turn(request):
        with pytest.raises(AppError, match="上一条"):
            with app.state.agent_memory.turn(request):
                pass
    assert not app.state.agent_memory.entries[identifier].busy


def test_memory_turn_and_character_budget(exam_app):
    app, client, course, _ = exam_app
    memory = app.state.agent_memory
    memory.max_turns, memory.max_chars = 2, 1000
    payload = dict(course_id=course, session_id=uuid4().hex)
    for _ in range(4):
        client.post("/api/agent", json=dict(payload, question="A*是什么？"))
    entry = memory.entries[payload["session_id"]]
    assert len(entry.turns) <= 2
    assert len(json.dumps(entry.turns, ensure_ascii=False)) <= 1000
