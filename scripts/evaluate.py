"""小型、文档级检索评估；生成真实测量结果，不预设目标分数。"""

import argparse
import json
import statistics
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from scripts.make_fixtures import generate


def evaluate(mode: str, output: Path):
    cases = json.loads(
        (Path(__file__).resolve().parents[1] / "tests/fixtures/queries.json").read_text(
            encoding="utf-8"
        )
    )
    results = []
    with tempfile.TemporaryDirectory(prefix="studyagent-eval-") as directory:
        root = Path(directory)
        settings = Settings(study_mode=mode, data_dir=root / "db")
        with TestClient(create_app(settings)) as client:
            course = client.post("/api/courses", json={"name": "自编测试课程"}).json()["id"]
            ids, chunk_count = {}, 0
            for path in generate(root / "samples"):
                with path.open("rb") as file:
                    response = client.post(
                        f"/api/courses/{course}/documents", files={"file": (path.name, file)}
                    )
                response.raise_for_status()
                doc = response.json()
                ids[path.name] = doc["id"]
                chunk_count += doc["chunk_count"]
            for case in cases:
                payload = {"course_id": course, "question": case["question"]}
                if case.get("document_names"):
                    payload["document_ids"] = [ids[name] for name in case["document_names"]]
                search = client.post("/api/search", json=payload)
                chat = client.post("/api/chat", json=payload)
                error = not search.is_success or not chat.is_success
                sources = search.json().get("sources", [])
                # 指标标注粒度是文档，不应误称为 Chunk 级 Recall。
                retrieved = list(dict.fromkeys(source["document_name"] for source in sources))
                expected = set(case["expected_sources"])
                hits = expected.intersection(retrieved)
                ranks = [i + 1 for i, name in enumerate(retrieved) if name in expected]
                response = chat.json()
                results.append(
                    {
                        "id": case["id"],
                        "split": case["split"],
                        "question": case["question"],
                        "expected_sources": sorted(expected),
                        "retrieved_sources": retrieved,
                        "recall_at_k": len(hits) / len(expected) if expected else None,
                        "hit_at_k": int(bool(hits)) if expected else None,
                        "reciprocal_rank": 1 / min(ranks) if ranks else (0 if expected else None),
                        "search_retrieval_ms": search.json().get("retrieval_ms"),
                        "retrieval_ms": response.get("retrieval_ms"),
                        "total_ms": response.get("total_ms"),
                        "llm_ms": response.get("llm_ms"),
                        "usage": response.get("usage"),
                        "error": error,
                        "answer": response.get("answer"),
                        "qa_insufficient_evidence": response.get("insufficient_evidence")
                        if mode == "api"
                        else None,
                        "expected_keywords": case["expected_keywords"],
                        "human_correctness": None,
                        "human_citation_support": None,
                    }
                )

    def summarize(items):
        answerable = [item for item in items if item["expected_sources"]]

        def mean_or_none(values):
            values = [value for value in values if value is not None]
            return statistics.mean(values) if values else None

        return {
            "queries": len(items),
            "answerable_queries": len(answerable),
            "document_recall_at_k": statistics.mean(x["recall_at_k"] for x in answerable),
            "document_hit_rate_at_k": statistics.mean(x["hit_at_k"] for x in answerable),
            "document_mrr": statistics.mean(x["reciprocal_rank"] for x in answerable),
            "retrieval_ms_mean": mean_or_none(x["retrieval_ms"] for x in items),
            "total_ms_mean": mean_or_none(x["total_ms"] for x in items),
            "error_rate": sum(x["error"] for x in items) / len(items),
        }

    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "dataset": "自编三格式合成资料；文档级标注；不代表真实课程效果",
        "qa_status": "需要人工核查答案与来源支持关系" if mode == "api" else "未执行真实 LLM QA",
        "document_count": 3,
        "chunk_count": chunk_count,
        "configuration": {
            "chunk_size": settings.chunk_size,
            "overlap": settings.chunk_overlap,
            "top_k": settings.retrieval_top_k,
            "threshold": settings.min_similarity,
        },
        "all": summarize(results),
        "dev": summarize([x for x in results if x["split"] == "dev"]),
        "test": summarize([x for x in results if x["split"] == "test"]),
        "results": results,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"mode": mode, "output": str(output), **report["all"]}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["demo", "api"], default="demo")
    parser.add_argument("--output", type=Path, default=Path("data/evaluation-demo.json"))
    args = parser.parse_args()
    evaluate(args.mode, args.output)
