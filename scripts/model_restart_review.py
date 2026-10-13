"""Continue a synthetic model conversation from the earlier process; no user documents."""

import json
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select

from app.core.config import Settings
from app.main import create_app
from app.models import AgentContext
from app.services.connection import model_services


def main():
    profile = json.loads(Path("data/model-connection.json").read_text(encoding="utf-8"))
    settings = Settings(
        _env_file=None,
        auth_enabled=False,
        data_dir=Path("data/model-learning-smoke"),
        min_similarity=0,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        configured = settings.model_copy(
            update=dict(
                study_mode="api",
                llm_base_url=profile["base_url"],
                llm_model=profile["model"],
                llm_api_key=SecretStr(profile["api_key"]),
            )
        )
        app.state.connection._bind(model_services(app.state, configured))
        with app.state.sessions() as db:
            contexts = list(
                db.scalars(select(AgentContext).order_by(AgentContext.updated_at.desc()))
            )
            row = next(
                row
                for row in contexts
                if len(row.payload["turns"]) >= 3
                and row.payload["turns"][0]["question"] == "根据层次聚类出两道题目"
            )
            identifier, course = row.id, row.course_id
            documents = row.payload["scope"][1]
        params = dict(course_id=course, document_ids=documents)
        snapshot = client.get(f"/api/agent/sessions/{identifier}", params=params).json()
        before = len(snapshot["turns"])
        assert before >= 3 and not snapshot["context_reset"]
        response = client.post(
            "/api/agent",
            json=dict(
                course_id=course,
                document_ids=documents,
                session_id=identifier,
                question="再来一道题",
            ),
        )
        assert response.status_code == 200
        result = response.json()
        assert (
            result["artifacts"]
            and result["context_turns"] == min(before + 1, 10)
            and not result["context_reset"]
        )
        artifact = client.get(
            f"/api/courses/{course}/artifacts/{result['artifacts'][0]['id']}"
        ).json()
        assert len(artifact["content"]["questions"]) == 1
        assert any("层次聚类" in topic for topic in artifact["request"]["topics"])
        assert all(source["document_id"] in documents for source in artifact["sources"])
        report = dict(
            model=profile["model"],
            restored_turns=before,
            continued_turns=result["context_turns"],
            retained_topic=True,
            question_count=1,
            source_scope_preserved=True,
            usage=result["usage"],
            success=True,
        )
        Path("docs/evaluation-model-context-restart.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
