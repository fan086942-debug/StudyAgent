"""在临时课程上测量工具首选准确率与链路，demo 指标不代表真实模型效果。"""

import argparse
import json
import statistics
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from scripts.make_exam_fixtures import generate as generate_exams
from scripts.make_fixtures import generate as generate_knowledge


def evaluate(mode: str) -> dict:
    cases = json.loads(
        (Path(__file__).resolve().parents[1] / "tests/fixtures/agent_queries.json").read_text(
            encoding="utf-8"
        )
    )
    with tempfile.TemporaryDirectory(prefix="studyagent-eval-", ignore_cleanup_errors=True) as temp:
        root = Path(temp)
        settings = Settings(
            _env_file=".env" if mode == "api" else None, study_mode=mode, data_dir=root / "db"
        )
        rows = []
        with TestClient(create_app(settings)) as client:
            course = client.post("/api/courses", json={"name": "Agent 自编评估课程"}).json()["id"]
            for kind, paths in [
                ("textbook", generate_knowledge(root / "knowledge")),
                ("exam", generate_exams(root / "exams")),
            ]:
                for path in paths:
                    response = client.post(
                        f"/api/courses/{course}/documents",
                        files={"file": (path.name, path.read_bytes())},
                        data={"document_type": kind},
                    )
                    response.raise_for_status()
            papers = client.get(f"/api/courses/{course}/papers").json()
            if any(p["status"] != "ready" for p in papers):
                raise RuntimeError(
                    "评估试卷解析失败；请先核对配置和模型返回，不能将失败夹具计为路由得分"
                )
            for case in cases:
                response = client.post(
                    "/api/agent", json={"course_id": course, "question": case["question"]}
                )
                response.raise_for_status()
                result = response.json()
                chain = [step["tool"] for step in result["trace"]]
                rows.append(
                    {
                        **case,
                        "actual_chain": chain,
                        "first_tool_correct": bool(chain and chain[0] == case["expected_tool"]),
                        "chain_exact_match": chain == case["expected_chain"]
                        if "expected_chain" in case
                        else None,
                        "finish_reason": result["finish_reason"],
                        "total_ms": result["total_ms"],
                        "usage": result["usage"],
                        "source_count": len(result["sources"]),
                        "question_count": len(result["questions"]),
                        "answer": result["answer"],
                        "manual_answer_correct": None,
                    }
                )
        return {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "mode": mode,
            "note": "12条自编小样本；demo是确定性规则路由，不代表LLM Tool Selection Accuracy。API模式需另行实测并人工审核答案。",
            "cases": len(rows),
            "documents": 6,
            "papers": len(papers),
            "questions": sum(p["question_count"] for p in papers),
            "first_tool_accuracy": sum(row["first_tool_correct"] for row in rows) / len(rows),
            "average_total_ms": statistics.mean(row["total_ms"] for row in rows),
            "stopped_or_failed_rate": sum(
                row["finish_reason"] not in {"completed", "insufficient_evidence"} for row in rows
            )
            / len(rows),
            "results": rows,
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["demo", "api"], default="demo")
    parser.add_argument("--output", type=Path, default=Path("data/evaluation-agent-demo.json"))
    args = parser.parse_args()
    report = evaluate(args.mode)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {key: value for key, value in report.items() if key not in {"results", "note"}},
            ensure_ascii=False,
        )
    )
