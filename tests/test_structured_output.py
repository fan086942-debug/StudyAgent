import json

import httpx
import pytest

from app.agent.planner import APIPlanner
from app.core.config import Settings
from app.core.errors import AppError
from app.llm.generation_provider import GenerationProvider
from app.schemas.generation import StudyGenerationTask
from tests.test_material_study import model_pack_content


def completion(content, **extra):
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content}, **extra}],
            "usage": {"total_tokens": 10},
        },
    )


def test_agent_json_mode_fences_and_bounded_repair():
    requests = []

    def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        assert payload["response_format"] == {"type": "json_object"}
        if len(requests) == 1:
            return completion("已检索到原文，但本条输出不是约定的 JSON。")
        return completion(
            '```json\n{"answer":"测试结论 [S1]","citation_ids":["S1"],"insufficient_evidence":false}\n```'
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        result = APIPlanner(Settings(_env_file=None), http).step(
            [{"role": "user", "content": "概念解释"}], []
        )
    assert result.final.answer == "测试结论 [S1]" and result.usage["total_tokens"] == 20
    assert len(requests) == 2
    assert "结构校验" in requests[1]["messages"][-1]["content"]


def test_agent_bad_final_is_not_reported_as_missing_tool_support():
    requests = []

    def handler(request):
        requests.append(request)
        return completion("still invalid")

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(AppError) as error:
            APIPlanner(Settings(_env_file=None), http).step(
                [{"role": "user", "content": "问题"}], []
            )
    assert len(requests) == 2 and error.value.usage["total_tokens"] == 20
    assert "Tool Calling" not in error.value.message


def test_truncation_stops_without_blind_repeat_and_preserves_usage():
    requests = []

    def handler(request):
        requests.append(request)
        return completion('{"title":"partial', finish_reason="length")

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        provider = GenerationProvider(Settings(_env_file=None), http)
        with pytest.raises(AppError) as error:
            provider.generate(StudyGenerationTask(kind="review", topics=["主题"]), {})
    assert len(requests) == 1 and error.value.code == "generation_output_truncated"
    assert error.value.usage["total_tokens"] == 10


def test_generation_repairs_schema_and_keeps_external_citations_validation():
    requests = []

    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        assert body["response_format"] == {"type": "json_object"}
        if len(requests) == 1:
            return completion('{"title":"主题", "sections":"wrong shape"}')
        return completion(
            json.dumps(
                dict(
                    title="主题",
                    sections=[
                        dict(topic="主题", summary="总结", key_points=["要点"], citation_ids=["S1"])
                    ],
                )
            )
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        content, usage = GenerationProvider(Settings(_env_file=None), http).generate(
            StudyGenerationTask(kind="review", topics=["主题"]), {}
        )
    assert content.sections[0].citation_ids == ["S1"] and usage["total_tokens"] == 20


def test_failed_study_resumes_valid_chapters_and_records_actual_usage(exam_app):
    from tests.test_material_study import study_book_bytes

    app, client, course, _ = exam_app
    upload = client.post(
        f"/api/courses/{course}/documents", files={"file": ("resume.docx", study_book_bytes())}
    )
    book = upload.json()["id"]
    app.state.generation.settings.study_mode = "api"
    app.state.agent.settings.study_mode = "api"
    calls = []

    def handler(request):
        data = json.loads(json.loads(request.content)["messages"][1]["content"])
        calls.append(data)
        if len(calls) == 4:
            return completion('{"title":"partial', finish_reason="length")
        return completion(json.dumps(model_pack_content(data, len(calls)), ensure_ascii=False))

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        app.state.generation.provider.client = http
        args = dict(course_id=course, document_ids=[book], question="总结这份资料各章知识点")
        first = client.post("/api/agent", json=args).json()
        assert first["finish_reason"] == "study_failed" and first["usage"]["total_tokens"] == 40
        assert client.get(f"/api/courses/{course}/artifacts").json() == []
        second = client.post("/api/agent", json=args).json()
        assert second["artifacts"]
        artifact = client.get(
            f"/api/courses/{course}/artifacts/{second['artifacts'][0]['id']}"
        ).json()
        assert artifact["coverage"]["cached_summaries"] == 3
        assert artifact["usage"]["total_tokens"] == 60
        assert len(calls) == 10
    root = app.state.generation.settings.data_dir / "study-cache"
    assert list(root.rglob("*.json"))
    assert client.delete(f"/api/documents/{book}").status_code == 200
    assert not list(root.rglob("*.json"))
