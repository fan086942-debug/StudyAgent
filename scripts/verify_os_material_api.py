"""Isolated real-model acceptance for the reported operating-systems PDF failures."""

import argparse
import json
import logging
import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.errors import AppError
from app.main import create_app
from app.schemas.connection import ConnectionInput
from app.services.connection import model_services


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--connection", type=Path, default=Path("data/model-connection.json"))
    parser.add_argument("--output", type=Path, default=Path("data/os-pdf-debug/acceptance.json"))
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    profile = ConnectionInput.model_validate_json(args.connection.read_text("utf-8"))
    report = dict(model=profile.model, cases={}, validation_failures=[], provider_calls=[],
                  source_root=str(Path(create_app.__code__.co_filename).resolve()))
    started = time.perf_counter()

    def save():
        report["seconds"] = round(time.perf_counter()-started, 2)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")

    logging.getLogger("httpx").setLevel(logging.WARNING)
    with tempfile.TemporaryDirectory(prefix="os-pdf-api-", dir=args.output.parent) as directory:
        settings = Settings(_env_file=None, data_dir=Path(directory), require_real_model=True,
                            auth_enabled=False, request_timeout=120)
        app = create_app(settings)
        with TestClient(app) as client:
            app.state.connection._bind(model_services(app.state, app.state.connection._settings(profile)))
            app.state.connection.profile = profile
            service = app.state.generation
            original_validate = service._validate
            original_post = app.state.http.post

            def validate(*values, **kwargs):
                try:
                    return original_validate(*values, **kwargs)
                except AppError as exc:
                    report["validation_failures"].append(dict(
                        request=values[0].model_dump(), content=values[1].model_dump(),
                        topic_ids=values[2], allowed_headings=kwargs.get("allowed_headings"),
                        code=exc.code, message=exc.message))
                    save()
                    raise

            def observed_post(url, **kwargs):
                response = original_post(url, **kwargs)
                entry = dict(endpoint=url.rsplit("/", 1)[-1], status=response.status_code)
                if response.status_code == 200:
                    entry["usage"] = response.json().get("usage", {})
                report["provider_calls"].append(entry)
                return response

            service._validate = validate
            app.state.http.post = observed_post
            course = client.post("/api/courses", json={"name": "操作系统引论问题复现"}).json()["id"]
            uploaded = client.post(f"/api/courses/{course}/documents",
                                   files={"file": (args.pdf.name, args.pdf.read_bytes())},
                                   data={"document_type": "slides"})
            uploaded.raise_for_status()
            document = uploaded.json()["id"]
            report["document"] = uploaded.json()
            print("PDF indexed", flush=True)

            def case(name, endpoint, body):
                tick = time.perf_counter()
                response = client.post(endpoint, json=dict(course_id=course, document_ids=[document], **body))
                result = response.json()
                passed = response.status_code in {200, 201}
                artifact = result
                if endpoint == "/api/agent":
                    passed = passed and result["finish_reason"] == "completed" and bool(result["sources"])
                    passed = passed and result["answer_basis"] in {"materials", "mixed"}
                    passed = passed and any(110 <= s["page"] <= 133 for s in result["sources"])
                else:
                    passed = passed and bool(artifact.get("content", {}).get("sections"))
                    if name == "topic_review":
                        passed = passed and any(110 <= s["page"] <= 133 for s in artifact.get("sources", []))
                        passed = passed and all(s["pitfalls"] for s in artifact.get("content", {}).get("sections", []))
                    if passed:
                        base = f"/api/courses/{course}/artifacts/{artifact['id']}"
                        exported = client.get(base + "/download")
                        passed = exported.status_code == 200
                        (args.output.parent / f"{name}.md").write_text(exported.text, "utf-8")
                report["cases"][name] = dict(passed=bool(passed), status=response.status_code,
                                              seconds=round(time.perf_counter()-tick, 2), response=result)
                save()
                print(f"{'PASS' if passed else 'FAIL'} {name}", flush=True)

            case("topic_review", "/api/generate", dict(kind="review", topics=["操作系统的功能与特征"]))
            case("source_grounded_question", "/api/agent", dict(
                question="操作系统的功能与特征章节中的处理机调度包括几个方面？"))
            case("whole_material_summary", "/api/study", dict(include_questions=False))
    report["passed"] = all(c["passed"] for c in report["cases"].values())
    report["total_tokens"] = sum(c.get("usage", {}).get("total_tokens", 0) for c in report["provider_calls"])
    save()
    print(json.dumps(dict(passed=report["passed"], total_tokens=report["total_tokens"],
                          seconds=report["seconds"]), ensure_ascii=False), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
