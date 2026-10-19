import json

import httpx
import pytest

from app.agent.intents import (
    generation_requested,
    question_count,
    study_intent,
    topic_generation_intent,
)
from app.agent.tools import ToolContext
from app.core.errors import AppError
from app.schemas.chat import SearchRequest
from tests.test_agent import ScriptedPlanner
from tests.test_exams import exam_bytes


@pytest.mark.parametrize("question", [
    "解释第2.10题，给出题干、参考答案和教材依据。",
    "请给出教材中这道题的参考答案",
    "指出题目中与教材矛盾的地方",
])
def test_existing_question_answer_is_not_new_exam_generation(question):
    assert generation_requested(question) is False
    assert study_intent(question) is None
    assert topic_generation_intent(question) is None


def test_explicit_question_count_still_requests_generation():
    assert generation_requested("根据教材给出两道题") is True
    assert study_intent("根据教材给出两道题")["question_count"] == 2


@pytest.mark.parametrize(
    "question,count,topic",
    [
        ("根据层次聚类出两道题目", 2, "层次聚类"),
        ("给我出两道层次聚类的题目", 2, "层次聚类"),
        ("请根据层次聚类生成2道简答题", 2, "层次聚类"),
        ("关于层次聚类，出二题", 2, "层次聚类"),
        ("生成 A* 模拟卷 2道简答题", 2, "A*"),
        ("根据出入栈出两道题目", 2, "出入栈"),
        ("根据间隔复习出两道题目", 2, "间隔复习"),
        ("根据层次聚类出两道题目，并提供答案与解析", 2, "层次聚类"),
        ("给我出两道层次聚类的题目，附参考答案", 2, "层次聚类"),
        ("根据层次聚类出题", 3, "层次聚类"),
        ("基于朴素贝叶斯出十二道题目", 12, "朴素贝叶斯"),
    ],
)
def test_explicit_topic_requests(question, count, topic):
    tool, args = topic_generation_intent(question)
    assert tool == "generate_mock_exam"
    assert args["topics"] == [topic] and args["question_count"] == count
    assert generation_requested(question)


@pytest.mark.parametrize(
    "question",
    [
        "层次聚类的概念是什么？",
        "查找层次聚类的两道历史题",
        "层次聚类怎么考？",
        "不要出两道题，只解释层次聚类",
        "不要生成层次聚类试卷",
        "层次聚类出现在两道题中吗？",
    ],
)
def test_search_and_negation_are_not_generation(question):
    assert topic_generation_intent(question) is None
    assert not generation_requested(question)


def test_options_and_material_routing():
    for topic in ("整数问题", "基础函数", "出入栈"):
        assert topic_generation_intent(f"根据{topic}出两道题目")[1]["topics"] == [topic]
    _, args = topic_generation_intent("根据层次聚类出两道进阶计算题")
    assert args == dict(
        topics=["层次聚类"], question_count=2, question_type="calculation", difficulty="hard"
    )
    assert topic_generation_intent("生成 A* 复习资料")[0] == "generate_review"
    assert study_intent("根据教材每章节重点出两道题目")["question_count"] == 2
    assert study_intent("总结教材重点，不要出两道题")["include_questions"] is False
    assert question_count("二十一道题") == 21


def test_agent_topic_request_calls_model_and_persists_two_questions(exam_app):
    app, client, course, exam = exam_app
    uploaded = client.post(
        f"/api/courses/{course}/documents",
        files={
            "file": (
                "合成层次聚类资料.docx",
                exam_bytes(
                    "凝聚层次聚类从单点簇开始，合并距离最近的簇。\n单链接取跨簇点对的最小距离，完全链接取最大距离。"
                ),
            )
        },
        data={"document_type": "textbook"},
    )
    document = uploaded.json()["id"]
    app.state.agent.planner = ScriptedPlanner([])  # Generation must not depend on planner searches.
    app.state.agent.settings.study_mode = "api"
    seen = []

    def model(request):
        payload = json.loads(request.content)
        task = json.loads(payload["messages"][1]["content"])
        seen.append(task)
        # Use the real GenerationProvider and validation contract, with synthetic answers.
        topic = task["task"]["topics"][0]
        cite = task["evidence"]["topics"][topic][0]
        content = dict(
            title="层次聚类练习",
            questions=[
                dict(
                    topic=topic,
                    type="short_answer",
                    difficulty="medium",
                    stem=stem,
                    answer=answer,
                    explanation=answer,
                    citation_ids=[cite],
                )
                for stem, answer in [
                    ("凝聚层次聚类如何开始？", "从单点簇开始。"),
                    ("单链接和完全链接如何计算簇间距离？", "分别取跨簇点对距离的最小值和最大值。"),
                ]
            ],
        )
        return httpx.Response(
            200,
            json=dict(
                choices=[
                    dict(
                        message=dict(content=json.dumps(content, ensure_ascii=False)),
                        finish_reason="stop",
                    )
                ],
                usage=dict(total_tokens=42),
            ),
        )

    with httpx.Client(transport=httpx.MockTransport(model)) as http:
        app.state.generation.provider.client = http
        result = client.post(
            "/api/agent",
            json=dict(course_id=course, document_ids=[document], question="根据层次聚类出两道题目"),
        ).json()
    assert result["finish_reason"] == "completed", result
    assert [t["tool"] for t in result["trace"]] == ["generate_mock_exam"]
    assert result["usage"]["total_tokens"] == 42
    assert seen[0]["task"]["question_count"] == 2
    assert app.state.agent.planner.messages == []
    url = f"/api/courses/{course}/artifacts/{result['artifacts'][0]['id']}"
    artifact = client.get(url).json()
    assert len(artifact["content"]["questions"]) == 2
    assert artifact["request"]["topics"] == ["层次聚类"]
    assert {s["document_id"] for s in artifact["sources"]} == {document}
    assert "参考答案与解析" in client.get(url + "/download").text
    # Existing exam questions remain separate; generation does not manufacture historical questions.
    assert result["questions"] == []
    context = ToolContext(SearchRequest(course_id=course, question="不要出两道题，只解释层次聚类"))
    with pytest.raises(AppError, match="尚未要求"):
        app.state.agent.registry.execute(
            "generate_mock_exam", json.dumps(dict(topics=["层次聚类"], question_count=2)), context
        )
    denied = client.post(
        "/api/agent",
        json=dict(course_id=course, document_ids=[exam], question="根据层次聚类出两道题目"),
    ).json()
    assert (
        not denied["artifacts"]
        and denied["trace"][0]["observation"]["error"]["code"] == "generation_no_evidence"
    )
    for question in ("出两道题目", "根据层次聚类出零道题", "根据层次聚类出十三道题目"):
        failed = client.post("/api/agent", json=dict(course_id=course, question=question)).json()
        assert failed["trace"][0]["status"] == "error" and not failed["artifacts"]
