import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.main import create_app


def test_health(tmp_path):
    with TestClient(create_app(Settings(_env_file=None, data_dir=tmp_path))) as client:
        response = client.get("/health")
        assert response.json()["status"] == "ok"
        assert response.headers["x-request-id"]
        assert client.get("/").status_code == 200
        assert client.get("/static/app.js").status_code == 200


def test_invalid_config():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, chunk_overlap=800)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, study_mode="api")
