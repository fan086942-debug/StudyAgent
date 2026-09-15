import json

import httpx
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.rag.embedding import DemoEmbedding
from scripts.make_fixtures import generate
from tests.test_ingestion import upload


def test_api_transport_full_flow(tmp_path):
    """实际兼容 Provider + 模拟 HTTP，不是在线模型验收。"""
    settings = Settings(
        _env_file=None,
        study_mode="api",
        data_dir=tmp_path / "db",
        llm_api_key="test-only",
        embedding_api_key="test-only",
        llm_model="test-model",
        embedding_model="test-embedding",
        embedding_dimensions=2048,
        min_similarity=0.1,
    )
    demo = DemoEmbedding(Settings(_env_file=None))
    calls = []

    def server(request):
        calls.append(request.url.path)
        body = json.loads(request.content)
        if request.url.path.endswith("/embeddings"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"index": i, "embedding": vector}
                        for i, vector in enumerate(demo.embed(body["input"]))
                    ]
                },
            )
        evidence = json.loads(body["messages"][1]["content"])["evidence"]
        assert "id" in evidence[0] and "text" in evidence[0]
        answer = {
            "answer": "A* 使用 f(n)=g(n)+h(n)。 [S1]",
            "citation_ids": ["S1"],
            "insufficient_evidence": False,
        }
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps(answer)}}],
                "usage": {"total_tokens": 123},
            },
        )

    with httpx.Client(transport=httpx.MockTransport(server)) as mock:
        app = create_app(settings)
        with TestClient(app) as client:
            app.state.embeddings.client = mock
            app.state.qa.llm.client = mock
            course = client.post("/api/courses", json={"name": "AI"}).json()["id"]
            assert upload(client, course, generate(tmp_path / "fixtures")[0]).status_code == 201
            response = client.post("/api/chat", json={"course_id": course, "question": "A* 算法"})
            assert response.status_code == 200, response.text
            result = response.json()
            assert not result["insufficient_evidence"]
            assert result["sources"][0]["page"] == 1
            assert result["usage"]["total_tokens"] == 123
    assert "/v1/embeddings" in calls and "/v1/chat/completions" in calls
