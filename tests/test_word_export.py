import json
from io import BytesIO

import httpx
import pytest
from docx import Document

from app.llm.base import ModelAnswer
from tests.test_adaptive_answers import AnswerLLM
from tests.test_exams import exam_bytes


def read_word(response):
    assert response.status_code == 200, response.text[:300] if response.status_code != 200 else ""
    assert response.headers["content-type"].startswith("application/vnd.openxmlformats")
    assert response.headers["content-disposition"].endswith('.docx"')
    doc = Document(BytesIO(response.content))
    return "\n".join(p.text for p in doc.paragraphs)


@pytest.mark.parametrize("topic", ["进程", "缓存淘汰"])
def test_section_request_generates_exam_and_exports_complete_word(exam_app, topic, tmp_path):
    app, client, course, _ = exam_app
    response = client.post(f"/api/courses/{course}/documents", files={"file": (
        "独立主题资料.docx", exam_bytes(f"{topic}的概念与边界。\n{topic}包含定义、执行步骤、适用条件与检查方法。")
    )}, data={"document_type": "notes"})
    assert response.status_code == 201
    document = response.json()["id"]
    app.state.agent.settings.study_mode = "api"
    seen = []

    def handler(request):
        payload = json.loads(request.content)
        data = json.loads(payload["messages"][1]["content"])
        seen.append(data)
        assert data["task"]["topics"] == [topic]
        assert data["task"]["question_count"] == 5
        cite = data["evidence"]["topics"][topic][0]
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(dict(
            title=topic + "练习卷", questions=[dict(
                topic=topic, type="short_answer", difficulty="medium", stem=f"{topic}练习{index}？",
                answer=f"参考答案{index}。", explanation=f"解释{index}，请根据定义与适用条件核对。",
                citation_ids=[cite]) for index in range(1, 6)]
        ))}}], "usage": {"total_tokens": 88}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as provider:
        app.state.generation.provider.client = provider
        result = client.post("/api/agent", json=dict(course_id=course, document_ids=[document],
                            question=f"根据这{topic}这部分的知识点出一张试卷")).json()
        assert result["finish_reason"] == "completed", result
        assert [step["tool"] for step in result["trace"]] == ["generate_mock_exam"]
        artifact = result["artifacts"][0]["id"]
        url = f"/api/courses/{course}/artifacts/{artifact}/word"
        response = client.get(url + "?kind=qa")
        text = read_word(response)
        assert all(f"参考答案{i}" in text and f"解释{i}" in text for i in range(1, 6))
        assert "独立主题资料.docx" in text and "资料依据：[S" in text
        assert topic in read_word(client.get(url + "?kind=knowledge"))
        conversation = f"/api/courses/{course}/conversations/{result['conversation_id']}/word"
        assert "第 5 题" in read_word(client.get(conversation))
        assert len(seen) == 1  # Downloading never calls the model again.
        assert client.get(url + "?kind=unknown").status_code == 422
        other = client.post("/api/courses", json={"name": "其他课程"}).json()["id"]
        assert client.get(f"/api/courses/{other}/artifacts/{artifact}/word").status_code == 404
        assert client.get(f"/api/courses/{other}/conversations/{result['conversation_id']}/word").status_code == 404
        (tmp_path / "exam.docx").write_bytes(response.content)


def test_normal_answer_word_and_failed_answer_boundary(exam_app):
    app, client, course, _ = exam_app
    app.state.qa.settings.study_mode = "api"
    app.state.qa.llm = AnswerLLM(ModelAnswer(
        answer="先检查输入，再执行计算。", citation_ids=[], answer_basis="model", insufficient_evidence=False))
    result = client.post("/api/chat", json={"course_id": course, "question": "如何检查输入？"}).json()
    url = f"/api/courses/{course}/conversations/{result['conversation_id']}/word"
    assert "本次提问" in read_word(client.get(url))
    text = read_word(client.get(url + "?kind=knowledge"))
    assert "先检查输入" in text and "模型推理" in text
    app.state.qa.llm = AnswerLLM(ModelAnswer(
        answer="请补充输入。", citation_ids=[], answer_basis="unanswered", insufficient_evidence=True))
    result = client.post("/api/chat", json={"course_id": course, "question": "请计算？"}).json()
    assert client.get(f"/api/courses/{course}/conversations/{result['conversation_id']}/word").status_code == 409
