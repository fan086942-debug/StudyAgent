import json

import httpx
import pytest

from app.core.config import Settings
from app.core.errors import AppError
from app.llm.compatible_provider import CompatibleLLM, post_json
from app.rag.embedding import APIEmbedding, DemoEmbedding


def test_demo_vectors_deterministic():
    provider = DemoEmbedding(Settings(_env_file=None))
    first, second = provider.embed(["A* 启发式", "A* 启发式"])
    assert first == second
    assert sum(x * x for x in first) == pytest.approx(1)


def test_embedding_sort_and_validation():
    settings = Settings(_env_file=None, embedding_dimensions=2)
    rows = [{"index": 1, "embedding": [0, 1]}, {"index": 0, "embedding": [1, 0]}]
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"data": rows}))
    ) as client:
        provider = APIEmbedding(settings, client)
        assert provider.embed(["a", "b"]) == [[1, 0], [0, 1]]
        with pytest.raises(AppError, match="Embedding"):
            provider.embed(["a"])


def test_llm_structure_and_timeout():
    answer = {"answer": "使用队列 [S1]", "citation_ids": ["S1"], "insufficient_evidence": False}
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": json.dumps(answer)}}],
                    "usage": {"total_tokens": 30},
                },
            )
        )
    ) as client:
        result = CompatibleLLM(Settings(_env_file=None), client).generate("BFS?", [])
        assert result.content.citation_ids == ["S1"]
        assert result.usage["total_tokens"] == 30

    def timeout(request):
        raise httpx.ReadTimeout("secret should not be shown", request=request)

    with httpx.Client(transport=httpx.MockTransport(timeout)) as client:
        with pytest.raises(AppError, match="超时"):
            CompatibleLLM(Settings(_env_file=None), client).generate("a", [])


def test_llm_bad_json():
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"choices": [{"message": {"content": "not json"}}]}
            )
        )
    ) as client:
        with pytest.raises(AppError, match="回答结构"):
            CompatibleLLM(Settings(_env_file=None), client).generate("a", [])


def test_transient_retry_bounded_and_errors_redacted():
    calls = []

    def server(request):
        calls.append(1)
        return httpx.Response(503, text="sensitive upstream content")

    with httpx.Client(transport=httpx.MockTransport(server)) as client:
        with pytest.raises(AppError) as error:
            post_json(client, "https://example.invalid/test", "test-secret", {})
        assert len(calls) == 2
        assert "sensitive" not in error.value.message
        assert "test-secret" not in error.value.message
