from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.llm.base import GenerationResult, ModelAnswer
from app.main import create_app
from app.schemas.chat import SearchRequest, SearchResponse, Source
from app.services.qa import NO_EVIDENCE, QAService
from scripts.make_fixtures import generate
from tests.test_ingestion import upload


def test_retrieval_scope_persistence_and_demo(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path / "db", min_similarity=0.10)
    files = generate(tmp_path / "fixtures")
    with TestClient(create_app(settings)) as client:
        course = client.post("/api/courses", json={"name": "AI"}).json()["id"]
        other = client.post("/api/courses", json={"name": "Other"}).json()["id"]
        docs = [upload(client, course, path).json() for path in files]
        foreign = upload(client, other, files[0]).json()["id"]
        query = {"course_id": course, "question": "A* 算法"}
        search = client.post("/api/search", json=query).json()
        assert len({source["document_id"] for source in search["sources"]}) >= 2
        assert all(source["course_id"] == course for source in search["sources"])
        query["document_ids"] = [docs[1]["id"]]
        assert all(
            s["document_id"] == docs[1]["id"]
            for s in client.post("/api/search", json=query).json()["sources"]
        )
        query["document_ids"] = [foreign]
        assert client.post("/api/search", json=query).status_code == 400
        query.pop("document_ids")
        answer = client.post("/api/chat", json=query).json()
        assert answer["mode"] == "demo" and answer["sources"]
        assert "未调用 LLM" in answer["answer"]
    with TestClient(create_app(settings)) as client:
        assert client.post("/api/search", json=query).json()["sources"]


def test_qa_citation_and_insufficiency_guard():
    source = Source(
        citation_id="S1",
        chunk_id="c",
        course_id="course",
        document_id="d",
        document_name="a.pdf",
        document_type="textbook",
        file_type="pdf",
        score=0.8,
        text="BFS 使用队列",
        page=2,
        location_type="pdf_page",
        file_url="/file",
    )
    retrieval = SimpleNamespace(
        search=lambda request: SearchResponse(sources=[source], retrieval_ms=1)
    )
    request = SearchRequest(course_id="course", question="BFS?")
    settings = SimpleNamespace(study_mode="api")
    for text, ids, insufficient, expected in [
        ("使用队列 [S1]", ["S1"], False, "使用队列 [S1]"),
        ("使用队列 [S99]", ["S99"], False, NO_EVIDENCE),
        ("资料第999页 [S1]", ["S1"], False, NO_EVIDENCE),
        ("不知道", [], True, NO_EVIDENCE),
    ]:
        llm = SimpleNamespace(
            generate=lambda *args: GenerationResult(
                content=ModelAnswer(
                    answer=text, citation_ids=ids, insufficient_evidence=insufficient
                )
            )
        )
        response = QAService(settings, retrieval, llm).answer(request)
        assert response.answer == expected
        assert bool(response.sources) == (expected != NO_EVIDENCE)


def test_empty_course_refuses_without_llm(tmp_path):
    with TestClient(create_app(Settings(_env_file=None, data_dir=tmp_path))) as client:
        course = client.post("/api/courses", json={"name": "empty"}).json()["id"]
        result = client.post("/api/chat", json={"course_id": course, "question": "A*?"})
        assert result.json()["answer"] == NO_EVIDENCE
        assert result.json()["sources"] == []
