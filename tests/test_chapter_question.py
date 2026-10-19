import pytest

from app.agent.intents import referenced_question_number
from tests.test_adaptive_answers import AnswerLLM, model_answer
from tests.test_agent import ScriptedPlanner, call
from tests.test_exams import exam_bytes


@pytest.mark.parametrize("wording,number", [
    ("第四章第6个题目解答", "4.6"),
    ("请解答第4章第六题", "4.6"),
    ("第四章的第六道题怎么做？", "4.6"),
    ("第十二章习题第十一题解答", "12.11"),
    ("第三章第10题", "3.10"),
    ("请解答第4.6题", "4.6"),
    ("第４．６题解答", "4.6"),
    ("第四章出6道题", None),
    ("第四章第六节", None),
    ("计算4.6乘以3", None),
])
def test_reference_number(wording, number):
    assert referenced_question_number(wording) == number


def upload(client, course, text, kind="textbook", name="worksheet.docx"):
    response = client.post(
        f"/api/courses/{course}/documents",
        files={"file": (name, exam_bytes(text))}, data={"document_type": kind},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


TEXT = "第四章 内存管理\n4.5 解释分段管理。\n4.6 比较分页存储管理与分段存储管理的异同。\n4.7 说明段页式管理。"


@pytest.mark.parametrize("kind", ["exam", "textbook"])
def test_chapter_reference_reads_actual_stem_on_first_request(exam_app, kind):
    app, client, course, _ = exam_app
    document = upload(client, course, TEXT, kind)
    app.state.settings.study_mode = "api"
    app.state.settings.min_similarity = 1.0
    # The old planner refusal must never run before locating this explicit reference.
    app.state.agent.planner = ScriptedPlanner([])
    provider = AnswerLLM(model_answer())
    app.state.agent.registry.llm = provider
    result = client.post("/api/agent", json={
        "course_id": course, "document_ids": [document], "question": "第四章第6个题目解答",
    }).json()
    assert not result["insufficient_evidence"], result
    assert len(provider.calls) == 1
    question, evidence = provider.calls[0]
    assert "比较分页存储管理与分段存储管理的异同" in (
        question + "".join(source["text"] for source in evidence)
    )
    assert [step["tool"] for step in result["trace"]] == ["answer_question"]
    if kind == "exam":
        assert result["questions"][0]["number"] == "4.6"
        assert result["sources"][0]["document_id"] == document


def test_material_full_width_number_is_found_without_semantic_search(exam_app):
    app, client, course, _ = exam_app
    document = upload(client, course, TEXT.replace("4.6", "4．6"))
    app.state.settings.study_mode = "api"
    app.state.agent.planner = ScriptedPlanner([])
    provider = AnswerLLM(model_answer())
    app.state.agent.registry.llm = provider
    response = client.post("/api/agent", json={
        "course_id": course, "document_ids": [document], "question": "第四章第六道题解答",
    })
    assert not response.json()["insufficient_evidence"], response.text
    assert len(provider.calls) == 1


@pytest.mark.parametrize("kind", ["exam", "textbook"])
def test_duplicate_reference_requires_document_selection(exam_app, kind):
    app, client, course, _ = exam_app
    first = upload(client, course, TEXT, kind, "one.docx")
    second = upload(client, course, TEXT.replace("比较分页", "请对比分页"), kind, "two.docx")
    app.state.settings.study_mode = "api"
    app.state.agent.planner = ScriptedPlanner([])
    provider = AnswerLLM(model_answer())
    app.state.agent.registry.llm = provider
    request = {"course_id": course, "document_ids": [first, second], "question": "第四章第6个题目解答"}
    result = client.post("/api/agent", json=request).json()
    assert result["insufficient_evidence"] and "勾选" in result["answer"]
    assert provider.calls == []
    result = client.post("/api/agent", json={**request, "document_ids": [second]}).json()
    assert not result["insufficient_evidence"] and len(provider.calls) == 1


def test_missing_reference_does_not_use_different_chapter_or_course(exam_app):
    app, client, course, _ = exam_app
    document = upload(client, course, TEXT.replace("4.6", "14.6"))
    other = client.post("/api/courses", json={"name": "other"}).json()["id"]
    upload(client, other, TEXT, "exam")
    app.state.settings.study_mode = "api"
    app.state.agent.planner = ScriptedPlanner([])
    provider = AnswerLLM(model_answer())
    app.state.agent.registry.llm = provider
    result = client.post("/api/agent", json={
        "course_id": course, "document_ids": [document], "question": "第四章第6个题目解答",
    }).json()
    assert result["insufficient_evidence"] and "未找到题号 4.6" in result["answer"]
    assert provider.calls == []


def test_empty_course_reports_missing_upload_instead_of_calling_solver(exam_app):
    app, client, _, _ = exam_app
    course = client.post("/api/courses", json={"name": "empty"}).json()["id"]
    app.state.settings.study_mode = "api"
    app.state.agent.planner = ScriptedPlanner([])
    provider = AnswerLLM(model_answer())
    app.state.agent.registry.llm = provider
    result = client.post("/api/agent", json={
        "course_id": course, "question": "第四章第6个题目解答",
    }).json()
    assert result["insufficient_evidence"] and "先上传" in result["answer"]
    assert not provider.calls


def test_numbered_answer_tool_resolves_even_if_planner_drops_chapter(exam_app):
    app, client, course, _ = exam_app
    document = upload(client, course, TEXT, "exam")
    app.state.settings.study_mode = "api"
    app.state.agent.planner = ScriptedPlanner([call("answer_question", {"query": "解答第6题"})])
    provider = AnswerLLM(model_answer())
    app.state.agent.registry.llm = provider
    result = client.post("/api/agent", json={
        "course_id": course, "document_ids": [document], "question": "请解答第4.6题",
    }).json()
    assert not result["insufficient_evidence"]
    assert "比较分页存储管理与分段存储管理的异同" in provider.calls[0][0]
