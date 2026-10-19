import json

import httpx
import pytest
from sqlalchemy import select

from app.agent.planner import APIPlanner
from app.core.config import Settings
from app.core.errors import AppError
from app.llm.base import GenerationResult, ModelAnswer
from app.llm.exam_provider import ExamExtractor
from app.models import Question
from app.schemas.agent import AgentTurn
from app.schemas.exam import ExtractedQuestion, ExtractionBatch
from scripts.make_exam_fixtures import generate
from tests.test_agent import ScriptedPlanner, call
from tests.test_exams import exam_bytes


def test_exam_provider_validates_json_and_truncation():
    payload = {
        "questions": [
            {
                "number": "1",
                "type": "short_answer",
                "source_text": "1. 解释 A*",
                "knowledge_points": ["A*"],
            }
        ]
    }

    def handler(request):
        assert "原文" in json.loads(request.content)["messages"][0]["content"]
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(payload)}}]}
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert (
            ExamExtractor(Settings(_env_file=None), client)
            .extract("1. 解释 A*")
            .questions[0]
            .number
            == "1"
        )
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200, json={"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]}
            )
        )
    ) as client:
        with pytest.raises(AppError, match="题目结构"):
            ExamExtractor(Settings(_env_file=None), client).extract("test")


def test_api_extract_rejects_invented_text_atomically(exam_app):
    app, client, course, doc_id = exam_app
    app.state.exams.settings.study_mode = "api"

    class Extractor:
        def extract(self, text):
            return ExtractionBatch(
                questions=[ExtractedQuestion(number="99", source_text="99. 原卷不存在的题目")]
            )

    app.state.exams.extractor = Extractor()
    response = client.post(f"/api/documents/{doc_id}/extract-questions")
    assert response.status_code == 502 and response.json()["code"] == "exam_unverified_text"
    with app.state.sessions() as session:
        assert len(list(session.scalars(select(Question)))) == 2
    assert client.post(f"/api/courses/{course}/questions/search", json={}).json() == []


def test_exam_provider_corrects_copying_once_and_restores_source_order():
    text = "1.1 什么是进程？\n2.10 [必做]修改代码：\nwait(full);\nsignal(mutex);"
    first, second = text.split("\n", 1)
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        questions = ([{"number": "1.1", "source_text": "1.1 请解释进程。"}]
                     if len(calls) == 1 else [
                         {"number": "2.10", "source_text": second.replace("：", ":")},
                         {"number": "1.1", "source_text": first.replace("？", "?")},
                     ])
        return httpx.Response(200, json={"choices": [{"message": {
            "content": json.dumps({"questions": questions}),
        }}]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = ExamExtractor(Settings(_env_file=None), client).extract(text)
    assert len(calls) == 2
    assert calls[1]["messages"][-1]["role"] == "user"
    assert [question.number for question in result.questions] == ["1.1", "2.10"]
    assert [question.source_text for question in result.questions] == [first, second]


def test_exam_provider_still_rejects_fabrication_after_bounded_correction():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"choices": [{"message": {
            "content": json.dumps({"questions": [{
                "number": "1.1", "source_text": "1.1 编造题目。",
            }]}),
        }}]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AppError) as error:
            ExamExtractor(Settings(_env_file=None), client).extract("1.1 原文题目。")
    assert error.value.code == "exam_unverified_text" and len(calls) == 2


def test_multiformat_exam_extract_and_full_demo_chain(exam_app, tmp_path):
    app, client, course, _ = exam_app
    for path in generate(tmp_path / "samples"):
        response = client.post(
            f"/api/courses/{course}/documents",
            files={"file": (path.name, path.read_bytes())},
            data={"document_type": "exam"},
        )
        assert response.status_code == 201, response.text
    papers = client.get(f"/api/courses/{course}/papers").json()
    assert sorted(p["question_count"] for p in papers) == [1, 2, 6, 6]
    result = client.post(
        "/api/agent", json={"course_id": course, "question": "解释2025期末第12题"}
    ).json()
    assert [t["tool"] for t in result["trace"]] == [
        "search_questions",
        "get_question",
        "analyze_question",
    ]
    assert result["insufficient_evidence"] and result["questions"]
    primary = next(
        q for q in result["questions"] if q["number"] == "12" and "2025" in q["paper_name"]
    )
    analyzed = client.post(
        f"/api/questions/{primary['id']}/analyze", json={"course_id": course, "question": "分析"}
    )
    assert analyzed.status_code == 200 and "未调用 LLM" in analyzed.json()["answer"]


def test_native_api_multiple_turns_with_tool_error(exam_app):
    app, client, course, _ = exam_app
    calls = []

    def handler(request):
        payload = json.loads(request.content)
        calls.append(payload)
        if len(calls) == 1:
            message = {
                "tool_calls": [call("search_questions", {"query": "A*"}).calls[0].model_dump()]
            }
        else:
            observation = payload["messages"][-1]
            assert observation["role"] == "tool" and observation["tool_call_id"] == "call-1"
            message = {
                "content": json.dumps(
                    {
                        "answer": "找到了 A* 相关题目 [S1]",
                        "citation_ids": ["S1"],
                        "insufficient_evidence": False,
                    }
                )
            }
        return httpx.Response(
            200, json={"choices": [{"message": message}], "usage": {"total_tokens": 20}}
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        app.state.agent.settings.study_mode = "api"
        app.state.agent.planner = APIPlanner(app.state.settings, http)
        result = client.post(
            "/api/agent", json={"course_id": course, "question": "查 A* 试题"}
        ).json()
    assert result["finish_reason"] == "completed" and len(calls) == 2
    assert result["usage"]["total_tokens"] == 40


def test_context_and_provider_failure_return_trace(exam_app):
    app, client, course, _ = exam_app

    class FailedPlanner:
        def step(self, messages, tools):
            raise AppError("provider_timeout", "模型服务超时", 504)

    app.state.agent.planner = FailedPlanner()
    result = client.post("/api/agent", json={"course_id": course, "question": "查题"}).json()
    assert result["finish_reason"] == "provider_error" and result["insufficient_evidence"]
    app.state.agent.settings.agent_context_chars = 1
    app.state.agent.planner = ScriptedPlanner([AgentTurn()])
    result = client.post("/api/agent", json={"course_id": course, "question": "查题"}).json()
    assert result["finish_reason"] == "context_limit"


def test_question_analysis_uses_knowledge_and_validates_citations(exam_app):
    app, client, course, _ = exam_app
    client.post(
        f"/api/courses/{course}/documents",
        files={
            "file": (
                "知识讲义.docx",
                exam_bytes(
                    "A* 算法的评价函数是 f(n)=g(n)+h(n)，g(n)为已走路径代价，h(n)为剩余代价估计。"
                ),
            )
        },
        data={"document_type": "textbook"},
    ).raise_for_status()
    question = client.post(
        f"/api/courses/{course}/questions/search", json={"question_type": "choice"}
    ).json()[0]
    app.state.settings.study_mode = "api"
    calls = []

    class AnalysisLLM:
        def generate(self, prompt, evidence):
            calls.append((prompt, evidence))
            assert evidence and all("评价函数" in item["text"] for item in evidence)
            ref = evidence[0]["id"]
            return GenerationResult(
                content=ModelAnswer(
                    answer=f"参考答案：A。详细解析：评价函数为 g+h [{ref}]",
                    citation_ids=[ref],
                    insufficient_evidence=False,
                ),
                usage={"total_tokens": 42},
            )

    app.state.agent.registry.llm = AnalysisLLM()
    result = client.post(
        f"/api/questions/{question['id']}/analyze", json={"course_id": course, "question": "分析"}
    ).json()
    assert not result["insufficient_evidence"] and "参考答案：A" in result["answer"]
    assert result["usage"]["total_tokens"] == 42
    assert any(source["document_type"] == "textbook" for source in result["sources"])
    assert len(calls) == 1


def test_successful_api_extraction_preserves_locations(exam_app):
    app, client, course, doc_id = exam_app
    app.state.settings.study_mode = "api"

    class Extractor:
        def extract(self, text):
            return ExtractionBatch(
                questions=[
                    ExtractedQuestion(
                        number="1",
                        type="choice",
                        source_text="1. A* 的评价函数？（2分）【知识点：A*】\nA. g+h\nB. g-h",
                        options=["A. g+h", "B. g-h"],
                        score=2,
                        knowledge_points=["Ａ*", "A*"],
                        difficulty="easy",
                    )
                ]
            )

    app.state.exams.extractor = Extractor()
    response = client.post(f"/api/documents/{doc_id}/extract-questions")
    assert response.status_code == 200, response.text
    questions = client.post(f"/api/courses/{course}/questions/search", json={}).json()
    assert len(questions) == 1 and questions[0]["extraction_method"] == "llm"
    assert len(questions[0]["knowledge_points"]) == 1
    assert len(questions[0]["locations"]) == 3
