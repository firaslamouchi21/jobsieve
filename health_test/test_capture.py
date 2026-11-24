import json
import os
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

from jobsieve import db
from jobsieve import profile as prof
from jobsieve.api import api

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def client():
    return TestClient(api)


def payload(**kw):
    base = dict(
        url="https://www.bayt.com/en/uae/jobs/data-engineer-123/",
        title="Data Engineer",
        company="Acme",
        location="Dubai, AE",
        description="<p>Build <b>pipelines</b> in python.</p>",
        site="bayt.com",
    )
    return {**base, **kw}


class TestIngest:

    def test_saves_a_captured_job_with_a_source_label(self, client):
        r = client.post("/ingest", json=payload())
        assert r.status_code == 200 and r.json()["is_new"] is True
        job = db.list_jobs()[0]
        assert job["source"] == "capture:bayt.com" and job["title"] == "Data Engineer"
        assert job["description"] == "Build pipelines in python."

    def test_second_capture_of_the_same_page_updates_it(self, client):
        client.post("/ingest", json=payload())
        again = client.post("/ingest", json=payload(title="Data Engineer", company="Acme Ltd"))
        assert again.json()["is_new"] is False and db.count_jobs() == 1

    def test_without_a_profile_no_verdict_is_given(self, client):
        r = client.post("/ingest", json=payload()).json()
        assert r["eligibility"] is None and r["reasons"] == []

    def test_with_a_profile_the_job_is_judged_and_scored(self, client):
        prof.save({"home_country": "AE", "work_authorization": ["GCC"], "keywords": ["python"]})
        r = client.post("/ingest", json=payload()).json()
        assert r["eligibility"] == "eligible"
        assert r["score"] == 1
        assert db.list_jobs()[0]["eligibility"] == "eligible"

    def test_restrictions_from_the_page_are_used(self, client):
        prof.save({"home_country": "AE", "work_authorization": ["GCC"]})
        r = client.post("/ingest", json=payload(location="", remote=True, restrictions="United States")).json()
        assert r["eligibility"] == "not_eligible"

    def test_captured_jobs_stay_visible_in_the_latest_run_view(self, client):
        db.init()
        run_id = db.start_run()
        db.upsert_job("From search", "c", "https://x.com/1", "s", "", 5, "", run_id=run_id)
        client.post("/ingest", json=payload())
        titles = sorted(j["title"] for j in client.get("/jobs?run=latest").json()["jobs"])
        assert titles == ["Data Engineer", "From search"]

    @pytest.mark.parametrize("url", ["javascript:alert(1)", "file:///etc/passwd", "ftp://x.com/a", "not a url", ""])
    def test_only_web_addresses_are_accepted(self, client, url):
        assert client.post("/ingest", json=payload(url=url)).status_code == 422

    def test_missing_title_and_oversize_fields_are_rejected(self, client):
        assert client.post("/ingest", json=payload(title="")).status_code == 422
        assert client.post("/ingest", json=payload(description="x" * 60001)).status_code == 422
        assert client.post("/ingest", json=payload(title="x" * 301)).status_code == 422
        db.init()
        assert db.count_jobs() == 0

    def test_site_label_is_sanitised(self, client):
        client.post("/ingest", json=payload(site="evil site;DROP TABLE"))
        assert db.list_jobs()[0]["source"] == "capture:evilsitedroptable"

    def test_label_falls_back_to_the_url_host(self, client):
        client.post("/ingest", json=payload(site=""))
        assert db.list_jobs()[0]["source"] == "capture:bayt.com"

    def test_requires_the_token_when_one_is_set(self, client, monkeypatch):
        monkeypatch.setenv("API_TOKEN", "s3cret")
        assert client.post("/ingest", json=payload()).status_code == 401
        ok = client.post("/ingest", json=payload(), headers={"Authorization": "Bearer s3cret"})
        assert ok.status_code == 200

    def test_hostile_html_is_stored_as_plain_text(self, client):
        client.post("/ingest", json=payload(description='<script>alert(1)</script><img src=x onerror=alert(2)>Hi'))
        assert db.list_jobs()[0]["description"] == "Hi"


class TestLocationFromPageText:

    def test_missing_location_is_read_from_the_top_of_the_text(self, client):
        prof.save({"home_country": "AE", "work_authorization": ["GCC"]})
        r = client.post("/ingest", json=payload(location="", description="Data Engineer\nAIQU\nDubai, UAE\nPosted 25 days ago\nFull Time")).json()
        assert r["eligibility"] == "eligible"
        assert db.list_jobs()[0]["location"] == "Dubai, UAE"

    def test_an_elsewhere_location_in_the_text_is_not_eligible_when_onsite(self, client):
        prof.save({"home_country": "AE", "work_authorization": ["GCC"]})
        r = client.post("/ingest", json=payload(location="", description="Account Manager\nAustin, Texas\nOn-site role in our office.")).json()
        assert r["eligibility"] == "not_eligible"

    def test_places_far_down_the_page_are_ignored(self, client):
        text = "Data Engineer\n" + "x " * 300 + "We have offices in London."
        client.post("/ingest", json=payload(location="", description=text))
        assert not db.list_jobs()[0]["location"]

    def test_a_given_location_is_never_overridden(self, client):
        client.post("/ingest", json=payload(location="Cairo", description="Dubai, UAE"))
        assert db.list_jobs()[0]["location"] == "Cairo"


class TestUiLabel:

    def test_captured_label(self):
        pytest.importorskip("streamlit")
        from jobsieve.app import job_line

        assert "captured from bayt.com" in job_line({"company": "Acme", "source": "capture:bayt.com"})


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
class TestExtensionCore:

    def test_node_tests_pass(self):
        result = subprocess.run(
            ["node", "--test", os.path.join(ROOT, "extension", "test", "extract.test.js")],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    def test_manifest_asks_for_the_least_access(self):
        with open(os.path.join(ROOT, "extension", "manifest.json"), encoding="utf-8") as f:
            manifest = json.load(f)
        assert manifest["manifest_version"] == 3
        assert sorted(manifest["permissions"]) == ["activeTab", "scripting", "storage"]
        assert all(h.startswith(("http://localhost", "http://127.0.0.1")) for h in manifest["host_permissions"])
        assert "content_scripts" not in manifest and "background" not in manifest
