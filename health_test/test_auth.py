import pytest
from fastapi.testclient import TestClient

from jobsieve.api import api
from jobsieve import scraper


@pytest.fixture
def client():
    return TestClient(api)


PROTECTED = [
    ("get", "/status"),
    ("get", "/jobs"),
    ("get", "/export/json"),
    ("get", "/export/csv"),
    ("get", "/config"),
    ("post", "/pause"),
    ("post", "/resume"),
    ("post", "/stop"),
]


class TestNoTokenConfigured:

    def test_endpoints_are_open(self, client, monkeypatch):
        monkeypatch.delenv("API_TOKEN", raising=False)
        for method, path in PROTECTED:
            assert getattr(client, method)(path).status_code == 200, path


class TestTokenConfigured:

    @pytest.fixture(autouse=True)
    def token(self, monkeypatch):
        monkeypatch.setenv("API_TOKEN", "s3cret")

    def test_health_stays_open(self, client):
        assert client.get("/health").status_code == 200

    @pytest.mark.parametrize("method,path", PROTECTED)
    def test_missing_token_is_rejected(self, client, method, path):
        r = getattr(client, method)(path)
        assert r.status_code == 401
        assert r.headers["www-authenticate"] == "Bearer"

    def test_run_requires_token(self, client):
        assert client.post("/run", json={"keywords": ["python"]}).status_code == 401

    def test_wrong_token_is_rejected(self, client):
        r = client.get("/jobs", headers={"Authorization": "Bearer nope"})
        assert r.status_code == 401

    def test_non_bearer_scheme_is_rejected(self, client):
        r = client.get("/jobs", headers={"Authorization": "s3cret"})
        assert r.status_code == 401

    def test_correct_token_is_accepted(self, client):
        headers = {"Authorization": "Bearer s3cret"}
        for method, path in PROTECTED:
            assert getattr(client, method)(path, headers=headers).status_code == 200, path


class TestConfigEndpoint:

    def test_reports_which_provider_keys_exist_without_leaking_them(self, client, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "gsk-secret-value")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("API_TOKEN", raising=False)
        r = client.get("/config")
        assert r.json() == {
            "providers": {"groq": True, "anthropic": False, "gemini": False, "openai": False},
            "auth_required": False,
        }
        assert "gsk-secret-value" not in r.text
