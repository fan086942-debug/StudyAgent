import json

import httpx
import pytest

from app.agent.planner import APIPlanner
from app.agent.tools import ToolContext
from app.core.config import Settings
from app.core.errors import AppError
from app.llm.base import ModelAnswer
from app.schemas.agent import AgentTurn, FunctionCall, ToolCall
from app.schemas.chat import SearchRequest


class ScriptedPlanner:
    def __init__(self, turns):
        self.turns = iter(turns)
        self.messages = []

    def step(self, messages, tools):
        self.messages.append(list(messages))
        return next(self.turns)


def call(name, args, identifier="call-1"):
    return AgentTurn(
        calls=[
            ToolCall(id=identifier, function=FunctionCall(name=name, arguments=json.dumps(args)))
        ]
    )


def test_demo_routes_and_ambiguous_question(exam_app):
    app, client, course, _ = exam_app
    assert "generate_study_pack" in {tool["function"]["name"] for tool in client.get("/api/agent/tools").json()}
    for query, expected in [
        ("A* 是什么？", "search_knowledge"),
        ("教材哪里讲了 A*？", "locate_source"),
        ("A* 以前怎么考过？", "search_questions"),
    ]:
        result = client.post("/api/agent", json={"course_id": course, "question": query})
        assert result.status_code == 200, result.text
        assert result.json()["trace"][0]["tool"] == expected
    result = client.post(
        "/api/agent", json={"course_id": course, "question": "解释2025期末第1题"}
    ).json()
    assert len(result["questions"]) == 2
    assert [t["tool"] for t in result["trace"]] == ["search_questions"]
    assert "多道题" in result["answer"]


def test_real_loop_observations_citations_and_usage(exam_app):
    app, client, course, _ = exam_app
    planner = ScriptedPlanner(
        [
            call("search_questions", {"query": "A*"}),
            AgentTurn(
                final=ModelAnswer(
                    answer="找到有关 A* 的试题 [S1]",
                    citation_ids=["S1"],
                    insufficient_evidence=False,
                ),
                usage={"total_tokens": 30},
            ),
        ]
    )
    app.state.agent.planner = planner
    app.state.agent.settings.study_mode = "api"
    result = client.post("/api/agent", json={"course_id": course, "question": "A* 相关题"}).json()
    assert result["finish_reason"] == "completed" and not result["insufficient_evidence"]
    assert result["usage"]["total_tokens"] == 30
    assert result["sources"][0]["citation_id"] == "S1"
    observation = planner.messages[1][-1]
    assert observation["role"] == "tool" and observation["tool_call_id"] == "call-1"
    assert len(json.loads(observation["content"])["questions"]) == 2


def test_tool_error_recovery_and_limits(exam_app):
    app, client, course, _ = exam_app
    app.state.agent.planner = ScriptedPlanner(
        [
            call("nonexistent", {}),
            call("search_questions", {"query": "A*"}, "call-2"),
            AgentTurn(
                final=ModelAnswer(answer="没有依据", citation_ids=[], insufficient_evidence=True)
            ),
        ]
    )
    result = client.post("/api/agent", json={"course_id": course, "question": "test"}).json()
    assert [t["status"] for t in result["trace"]] == ["error", "ok"]
    app.state.agent.settings.agent_max_steps = 2
    app.state.agent.planner = ScriptedPlanner(
        [call("search_questions", {}, f"call-{i}") for i in range(3)]
    )
    result = client.post("/api/agent", json={"course_id": course, "question": "test"}).json()
    assert result["finish_reason"] == "step_limit"
    assert [t["status"] for t in result["trace"]] == ["ok", "cached"]


def test_scope_argument_guards_and_fabricated_citations(exam_app):
    app, client, course, doc_id = exam_app
    registry = app.state.agent.registry
    context = ToolContext(SearchRequest(course_id=course, question="test"))
    with pytest.raises(AppError, match="参数不合法"):
        registry.execute("search_knowledge", '{"query":"A*","course_id":"foreign"}', context)
    with pytest.raises(AppError, match="先搜索"):
        registry.execute("analyze_question", '{"question_id":"made-up"}', context)
    other = client.post("/api/courses", json={"name": "other"}).json()["id"]
    assert (
        client.post(
            "/api/agent", json={"course_id": other, "question": "test", "document_ids": [doc_id]}
        ).status_code
        == 400
    )
    app.state.agent.settings.study_mode = "api"
    app.state.agent.planner = ScriptedPlanner(
        [
            AgentTurn(
                final=ModelAnswer(
                    answer="无来源结论 [S99]", citation_ids=["S99"], insufficient_evidence=False
                )
            )
        ]
    )
    result = client.post("/api/agent", json={"course_id": course, "question": "test"}).json()
    assert result["finish_reason"] == "invalid_citations" and "无来源结论" not in result["answer"]


def test_native_tool_call_provider_contract():
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "id": "c1",
                                    "type": "function",
                                    "function": {
                                        "name": "locate_source",
                                        "arguments": '{"query":"A*"}',
                                    },
                                }
                            ]
                        }
                    }
                ]
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        planner = APIPlanner(Settings(_env_file=None), client)
        turn = planner.step([{"role": "user", "content": "A* 在哪里"}], [{"type": "function"}])
    assert turn.calls[0].function.name == "locate_source"
    assert requests[0]["tool_choice"] == "auto" and requests[0]["tools"]
