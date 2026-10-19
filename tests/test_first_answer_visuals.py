import json
from types import SimpleNamespace

import httpx
import pytest
from PIL import Image
from pypdf import PdfReader

from app.core.config import Settings
from app.llm.base import GenerationResult, ModelAnswer
from app.llm.compatible_provider import CompatibleLLM
from app.schemas.agent import AgentTurn
from app.schemas.chat import SearchRequest, Source
from app.services.answering import solve, valid_answer
from scripts.make_diagram_fixture import make_diagram_pdf
from tests.test_adaptive_answers import AnswerLLM, model_answer
from tests.test_agent import ScriptedPlanner, call


@pytest.mark.parametrize("retrieved_first", [False, True])
def test_first_request_recovers_from_planner_refusal(exam_app, retrieved_first):
    app, client, _, _ = exam_app
    course = client.post("/api/courses", json={"name": "no materials"}).json()["id"]
    app.state.settings.study_mode = "api"
    turns = [AgentTurn(final=ModelAnswer(
        answer="当前资料范围没有检索到足够依据。", insufficient_evidence=True,
    ))]
    if retrieved_first:
        turns.insert(0, call("search_knowledge", {"query": "A*"}))
    app.state.agent.planner = ScriptedPlanner(turns)
    provider = AnswerLLM(model_answer())
    app.state.agent.registry.llm = provider
    result = client.post("/api/agent", json={"course_id": course, "question": "请解释 A* 评价函数？"}).json()
    assert not result["insufficient_evidence"] and result["answer_basis"] == "model"
    assert result["trace"][-1]["tool"] == "answer_question"
    assert len(provider.calls) == 1
    assert result["sources"] == []


def test_direct_planner_answer_still_retrieves_then_solves(exam_app):
    app, client, course, _ = exam_app
    app.state.settings.study_mode = "api"
    app.state.agent.planner = ScriptedPlanner([AgentTurn(final=model_answer())])
    app.state.agent.registry.llm = AnswerLLM(model_answer())
    result = client.post("/api/agent", json={"course_id": course, "question": "A* 是什么？"}).json()
    assert not result["insufficient_evidence"]
    assert [step["tool"] for step in result["trace"]] == ["answer_question"]


@pytest.mark.parametrize("unique", [True, False])
def test_found_exam_question_is_solved_without_guessing_ambiguous_ids(exam_app, unique):
    app, client, course, _ = exam_app
    app.state.settings.study_mode = "api"
    args = {"question_type": "choice"} if unique else {"number": "1"}
    app.state.agent.planner = ScriptedPlanner([
        call("search_questions", args),
        AgentTurn(final=ModelAnswer(answer="没有教材依据。", insufficient_evidence=True)),
    ])
    provider = AnswerLLM(model_answer())
    app.state.agent.registry.llm = provider
    result = client.post("/api/agent", json={"course_id": course, "question": "请解答第1题"}).json()
    assert bool(provider.calls) is unique
    assert result["insufficient_evidence"] is not unique
    if unique:
        assert result["trace"][-1]["tool"] == "analyze_question"


def upload_pdf(client, course, path, document_type="exam"):
    response = client.post(
        f"/api/courses/{course}/documents",
        files={"file": (path.name, path.read_bytes())}, data={"document_type": document_type},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_saved_pdf_question_sends_real_page_not_only_ocr_text(exam_app, tmp_path):
    app, client, course, _ = exam_app
    path = make_diagram_pdf(tmp_path / "diagram.pdf")
    assert len(PdfReader(path).pages[0].extract_text()) > 300
    document = upload_pdf(client, course, path)
    question = client.post(f"/api/courses/{course}/questions/search", json={"number": "1.1"}).json()[0]
    app.state.settings.study_mode = "api"
    captured = []

    class VisionLLM:
        supports_images = True

        def solve(self, query, evidence, *, images=None):
            captured.extend(images)
            return GenerationResult(content=ModelAnswer(
                answer="P → T → Q → R", insufficient_evidence=False, answer_basis="model",
            ))

        generate = solve

    app.state.agent.registry.llm = VisionLLM()
    response = client.post(
        f"/api/questions/{question['id']}/analyze",
        json={"course_id": course, "question": "请解答第1.1题", "document_ids": [document]},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert not result["insufficient_evidence"] and result["answer_basis"] == "model"
    assert any(part["type"] == "image_url" for part in captured)
    import base64
    from io import BytesIO
    encoded = next(part["image_url"]["url"] for part in captured if part["type"] == "image_url")
    with Image.open(BytesIO(base64.b64decode(encoded.split(",", 1)[1]))) as picture:
        assert max(picture.size) <= app.state.settings.pdf_visual_max_edge
        assert picture.width > 1000
    assert result["sources"][0]["page"] == 1
    assert result["sources"][0]["document_type"] == "exam"


def test_visuals_reject_foreign_document_and_out_of_range_page(exam_app, tmp_path):
    app, client, course, _ = exam_app
    path = make_diagram_pdf(tmp_path / "scope.pdf")
    other = client.post("/api/courses", json={"name": "other"}).json()["id"]
    document = upload_pdf(client, other, path)
    source = Source(
        citation_id="S1", chunk_id="fake", course_id=course, document_id=document,
        document_name=path.name, document_type="exam", file_type="pdf",
        score=1, text="diagram", page=1, location_type="pdf_page", file_url="/file",
    )
    visuals = app.state.agent.registry.visuals
    provider = SimpleNamespace(supports_images=True)
    request = SearchRequest(course_id=course, question="解释这道图形题")
    assert visuals.prepare(request, [source], provider) == ([], None)
    own = upload_pdf(client, course, path)
    source.document_id = own
    source.page = 999
    images, warning = visuals.prepare(request, [source], provider)
    assert images == [] and "原图读取失败" in warning


def test_pdf_page_budget_and_disabled_vision_are_explicit(exam_app, tmp_path):
    from pypdf import PdfWriter

    app, client, course, _ = exam_app
    path = make_diagram_pdf(tmp_path / "diagram.pdf")
    reader = PdfReader(path)
    writer = PdfWriter()
    for _ in range(4):
        writer.add_page(reader.pages[0])
    multiple = tmp_path / "four-pages.pdf"
    writer.write(multiple)
    document = upload_pdf(client, course, multiple)
    sources = [Source(
        citation_id=f"S{page}", chunk_id=f"page-{page}", course_id=course,
        document_id=document, document_name=multiple.name, document_type="exam",
        file_type="pdf", score=1, text="question", page=page,
        location_type="pdf_page", file_url="/file",
    ) for page in range(1, 5)]
    request = SearchRequest(course_id=course, question="请分析图中通路")
    visuals = app.state.agent.registry.visuals
    visuals.settings.pdf_visual_max_pages = 2
    images, warning = visuals.prepare(request, sources, SimpleNamespace(supports_images=True))
    assert sum(part["type"] == "image_url" for part in images) == 2
    assert "最多核对 2 页" in warning
    images, warning = visuals.prepare(request, sources, SimpleNamespace(supports_images=False))
    assert images == [] and "仅使用提取文字" in warning


def test_provider_encodes_images_only_in_user_message():
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": model_answer().model_dump_json()}}]})

    settings = Settings(_env_file=None, pdf_visual_mode="enabled")
    parts = [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,dGVzdA==", "detail": "high"}}]
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = CompatibleLLM(settings, client)
        assert provider.supports_images
        provider.solve("读图", [], images=parts)
    assert isinstance(sent[0]["messages"][0]["content"], str)
    assert sent[0]["messages"][1]["content"][1:] == parts


def test_number_lookup_finds_pdf_image_when_uploaded_as_textbook(exam_app, tmp_path):
    app, client, course, _ = exam_app
    document = upload_pdf(client, course, make_diagram_pdf(tmp_path / "worksheet.pdf"), "textbook")
    app.state.retriever.settings.min_similarity = 1.0
    app.state.settings.study_mode = "api"
    app.state.agent.planner = ScriptedPlanner([AgentTurn(final=ModelAnswer(
        answer="没有找到历史试题。", insufficient_evidence=True,
    ))])
    captured = []

    class VisionLLM:
        supports_images = True

        def solve(self, query, evidence, *, images=None):
            assert evidence and "1.1 Follow" in evidence[0]["text"]
            captured.extend(images or [])
            return GenerationResult(content=ModelAnswer(
                answer="P → T → Q → R", insufficient_evidence=False, answer_basis="model",
            ))

        generate = solve

    app.state.agent.registry.llm = VisionLLM()
    result = client.post("/api/agent", json={
        "course_id": course, "document_ids": [document], "question": "请解答这份教材第1.1题",
    }).json()
    assert not result["insufficient_evidence"] and result["answer_basis"] == "model"
    assert any(part["type"] == "image_url" for part in captured)


@pytest.mark.parametrize("declared,inline,accepted", [
    ("S1", "", True),
    ("S99", "", False),
    ("S1", " [S99]", False),
    ("", "", True),
])
def test_missing_inline_marker_repairs_only_known_consistent_sources(declared, inline, accepted):
    source = Source(
        citation_id="S1", chunk_id="page-1", course_id="c", document_id="d",
        document_name="diagram.pdf", document_type="textbook", file_type="pdf",
        score=1, text="graph premise", page=1, location_type="pdf_page", file_url="/file",
    )
    provider = AnswerLLM(ModelAnswer(
        answer="通路为 P → T → Q → R。" + inline, citation_ids=[declared] if declared else [],
        answer_basis="materials", insufficient_evidence=False,
    ))
    answer = solve(provider, "读图", [source]).content
    assert valid_answer(answer, [source], allow_model=True) is accepted
    if accepted and declared:
        assert "资料依据：[S1]" in answer.answer
    elif not declared:
        assert answer.answer_basis == "model" and "[S" not in answer.answer
