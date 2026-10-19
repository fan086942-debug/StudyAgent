import pytest

from tests.test_exams import exam_app  # noqa: F401


@pytest.fixture(autouse=True)
def legacy_api_mode(monkeypatch):
    """Existing service tests exercise local mode; auth tests explicitly enable auth."""
    monkeypatch.setenv("AUTH_ENABLED", "false")
    # Deterministic unit tests use demo providers; the product defaults to real APIs.
    monkeypatch.setenv("REQUIRE_REAL_MODEL", "false")
