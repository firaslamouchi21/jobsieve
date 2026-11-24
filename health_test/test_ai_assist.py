import json

import pytest
from fastapi.testclient import TestClient

from jobsieve import ai_service, cli, db, scraper, tailor
from jobsieve import profile as prof
from jobsieve.ai_service import AIService
from jobsieve.api import api
from jobsieve.sources.base import JobRecord


class Reply:
    def __init__(self, content="", status=200):
        self.status_code, self._content = status, content

    def json(self):
        return {"choices": [{"message": {"content": self._content}}]}

    def raise_for_status(self):
        import requests
        if self.status_code >= 400:
            raise requests.HTTPError(f"http {self.status_code}", response=self)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL"):
        monkeypatch.delenv(name, raising=False)


class TestGenericProvider:

    def test_needs_a_model_and_either_a_key_or_a_local_address(self, monkeypatch):
        assert AIService("openai").enabled is False
        monkeypatch.setenv("OPENAI_MODEL", "gpt-x")
        assert AIService("openai").enabled is False
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        assert AIService("openai").enabled is True
        monkeypatch.delenv("OPENAI_API_KEY")
        monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:11434/v1")
        assert AIService("openai").enabled is True
        monkeypatch.setenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
        assert AIService("openai").enabled is False

    @pytest.mark.parametrize("url,local", [("http://localhost:1234/v1", True), ("http://127.0.0.1:11434/v1", True),
                                           ("http://host.docker.internal:11434/v1", True), ("https://api.openai.com/v1", False),
                                           ("https://localhost.evil.com/v1", False)])
    def test_local_addresses(self, url, local):
        assert ai_service.is_local_base_url(url) is local

    def test_posts_to_the_configured_address_without_a_key_for_local_models(self, monkeypatch):
        monkeypatch.setenv("OPENAI_MODEL", "llama3"); monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:11434/v1/")
        seen = []
        monkeypatch.setattr(ai_service.requests, "post", lambda url, headers, json, timeout: (seen.append((url, headers, json)), Reply('{"score": 7, "reasoning": "ok"}'))[1])
        assert AIService("openai").analyze("python job", "cv", ["python"]) == (7, "ok")
        url, headers, body = seen[0]
        assert url == "http://localhost:11434/v1/chat/completions" and headers == {} and body["model"] == "llama3"

    def test_retries_without_json_mode_when_the_server_rejects_it(self, monkeypatch):
        monkeypatch.setenv("OPENAI_MODEL", "m"); monkeypatch.setenv("OPENAI_API_KEY", "k")
        bodies = []

        def post(url, headers, json, timeout):
            bodies.append(dict(json))
            return Reply("", 400) if "response_format" in json else Reply('{"score": 4, "reasoning": "r"}')

        monkeypatch.setattr(ai_service.requests, "post", post)
        assert AIService("openai").analyze("text", "", ["x"]) == (4, "r")
        assert "response_format" in bodies[0] and "response_format" not in bodies[1]

    def test_other_providers_do_not_retry(self, monkeypatch):
        calls = []
        monkeypatch.setattr(ai_service.requests, "post", lambda *a, **k: (calls.append(1), Reply("", 400))[1])
        score, reasoning = AIService("groq", {"groq": "k"}).analyze("text", "", ["x"])
        assert reasoning.startswith("ai_failed:") and len(calls) == 1


class TestRunCostControls:

    @pytest.fixture
    def setup(self, monkeypatch):
        monkeypatch.setenv("MOCK_SEARCH", "true")
        calls = []
        monkeypatch.setattr(AIService, "enabled", property(lambda self: True))
        monkeypatch.setattr(AIService, "analyze", lambda self, text, cv, kw, profile=None: (calls.append(text), (9, "great fit"))[1])
        return calls

    def run(self, sources=("remoteok",), profile=None):
        if profile:
            prof.save(profile)
        scraper.try_lock()
        scraper.run_scrape("", False, provider="groq", api_keys={"groq": "k"}, sites=["example.com"], keywords=["python"],
                           cv_text="python dev", sources=list(sources), _lock_acquired=True)

    def test_unchanged_jobs_are_not_sent_to_the_model_again(self, setup):
        self.run()
        first = len(setup)
        assert first == 2
        self.run()
        assert len(setup) == first
        assert {j["score"] for j in db.list_jobs()} == {9}

    def test_a_changed_profile_or_cv_asks_again(self, setup):
        self.run()
        prof.save({"keywords": ["python"], "home_country": "AE"})
        self.run()
        assert len(setup) == 4

    def test_the_cap_limits_model_calls_per_run(self, setup, monkeypatch):
        monkeypatch.setattr(scraper, "AI_MAX_PER_RUN", 1)
        self.run()
        assert len(setup) == 1
        assert sorted(j["score"] for j in db.list_jobs()) != [9, 9]

    def test_ineligible_jobs_are_not_sent_to_the_model(self, setup, monkeypatch):
        from jobsieve import eligibility
        monkeypatch.setattr(eligibility, "evaluate", lambda job, profile: {
            "verdict": "not_eligible", "reasons": ["x"], "work_mode": "onsite", "seniority": "", "sponsorship": "",
            "salary_min": None, "salary_max": None, "salary_currency": ""})
        self.run(profile={"keywords": ["python"], "home_country": "AE"})
        assert setup == [] and len(db.list_jobs(eligibility=["not_eligible"])) == 2


GOOD = {"cv_suggestions": ["Lead with the Python pipeline work"], "keyword_gaps": ["Kubernetes"], "cover_letter": "Dear team, I built pipelines."}


class TestTailoring:

    @pytest.fixture
    def job(self, monkeypatch):
        monkeypatch.setenv("OPENAI_MODEL", "m"); monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:1/v1")
        prof.save({"cv_text": "Python engineer. Built pipelines for 3 years.", "keywords": ["python"]})
        db.init()
        record = JobRecord(title="Data Engineer", company="Acme", url="https://x/1", source="lever", location="Dubai",
                           description="Python and Kubernetes. 5 years wanted.")
        db.upsert_record(record, 5, "r", description=record.description)
        return db.record_hash(record)

    def reply(self, monkeypatch, payload):
        monkeypatch.setattr(ai_service.requests, "post", lambda *a, **k: Reply(payload if isinstance(payload, str) else json.dumps(payload)))

    def test_saves_the_result_and_flags_numbers_it_cannot_verify(self, job, monkeypatch):
        self.reply(monkeypatch, {**GOOD, "cover_letter": "I led 40 engineers for 3 years."})
        output = tailor.tailor_job(job, "openai", {})
        assert output["unverified_numbers"] == ["40"] and output["model"] == "m"
        assert db.get_job(job)["tailoring"]["keyword_gaps"] == ["Kubernetes"]

    def test_needs_a_cv_and_a_usable_model(self, job, monkeypatch):
        with pytest.raises(tailor.TailorError, match="no usable"):
            tailor.tailor_job(job, "groq", {"groq": ""})
        prof.save({"cv_text": ""})
        with pytest.raises(tailor.TailorError, match="CV"):
            tailor.tailor_job(job, "openai", {})

    @pytest.mark.parametrize("payload", ["not json", "[]", '{"cv_suggestions": []}'])
    def test_bad_model_output_is_an_error_not_a_crash(self, job, monkeypatch, payload):
        self.reply(monkeypatch, payload)
        with pytest.raises(tailor.TailorError, match="expected JSON"):
            tailor.tailor_job(job, "openai", {})
        assert db.get_job(job)["tailoring"] is None

    def test_prompt_forbids_inventing_things(self, job):
        text = tailor.build_prompt(db.get_job(job), "cv", {})
        assert "Do not invent" in text and "keyword_gaps" in text

    def test_api_and_markdown(self, job, monkeypatch):
        self.reply(monkeypatch, GOOD)
        client = TestClient(api)
        assert client.post("/jobs/nope/tailor", json={"provider": "openai"}).status_code == 404
        assert client.get(f"/jobs/{job}/tailor.md").status_code == 404
        r = client.post(f"/jobs/{job}/tailor", json={"provider": "openai"})
        assert r.status_code == 200 and r.json()["tailoring"]["cover_letter"].startswith("Dear")
        md = client.get(f"/jobs/{job}/tailor.md").text
        assert "# Data Engineer at Acme" in md and "Kubernetes" in md and "Cover letter draft" in md
        assert client.post(f"/jobs/{job}/tailor", json={"provider": "groq"}).status_code == 422

    def test_cli(self, job, monkeypatch, capsys, tmp_path):
        self.reply(monkeypatch, GOOD)
        out = tmp_path / "t.md"
        assert cli.main(["tailor", job[:10], "--provider", "openai", "--out", str(out)]) == 0
        assert "Cover letter draft" in out.read_text()
        assert cli.main(["tailor", "zzzzzzzzzz", "--provider", "openai"]) == 2


def test_config_reports_the_generic_provider(monkeypatch):
    client = TestClient(api)
    assert client.get("/config").json()["providers"]["openai"] is False
    monkeypatch.setenv("OPENAI_MODEL", "m"); monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:11434/v1")
    assert client.get("/config").json()["providers"]["openai"] is True
