import time

import pytest
from fastapi.testclient import TestClient

from jobsieve import db, scraper
from jobsieve.api import api
from jobsieve.sources import REGISTRY, SourceError

FEEDS = ["remoteok", "remotive", "arbeitnow"]


@pytest.fixture
def client():
    return TestClient(api)


def wait_for(client, messages, timeout=10.0, newer_than=0.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = client.get("/status").json()
        if data.get("message") in messages and data.get("timestamp", 0) > newer_than:
            return data
        time.sleep(0.05)
    return client.get("/status").json()


def start(client, **overrides):
    payload = {
        "provider": "groq",
        "lite_mode": True,
        "sites": ["example.com"],
        "keywords": ["python"],
        "cv_text": "",
        **overrides,
    }
    assert client.post("/run", json=payload).json()["started"] is True


class TestStructuredSourcesInRun:

    def test_each_feed_adds_its_jobs_with_details(self, client):
        start(client, sources=FEEDS)
        status = wait_for(client, {"complete"})
        assert status["message"] == "complete"
        assert status["added"] == 6
        jobs = client.get("/jobs").json()["jobs"]
        assert {j["source"] for j in jobs} == set(FEEDS)
        job = next(j for j in jobs if j["source"] == "remoteok")
        assert job["remote"] == 1
        assert job["location"] == "Remote"
        assert job["description"].startswith("python developer")
        assert job["company"].startswith("Mock Company")

    def test_progress_counts_one_task_per_feed(self, client):
        start(client, sources=["remoteok", "remotive"])
        assert wait_for(client, {"complete"})["progress"] == 100

    def test_default_sources_are_unchanged(self, client):
        start(client)
        status = wait_for(client, {"complete"})
        assert status["added"] == 1
        assert client.get("/jobs").json()["jobs"][0]["source"] == "ddg"

    def test_ddg_and_feeds_can_be_mixed(self, client):
        start(client, sources=["ddg", "remoteok"])
        assert wait_for(client, {"complete"})["added"] == 3

    def test_rerun_updates_instead_of_duplicating(self, client):
        start(client, sources=["remoteok"])
        first = wait_for(client, {"complete"})
        time.sleep(0.01)
        start(client, sources=["remoteok"])
        status = wait_for(client, {"complete"}, newer_than=first["timestamp"])
        assert status["added"] == 0
        assert db.count_jobs() == 2

    def test_cv_terms_score_full_descriptions(self, client):
        start(client, sources=["remoteok"], cv_text="python developer backend remote mock listing")
        wait_for(client, {"complete"})
        assert "cv_terms=" in client.get("/jobs").json()["jobs"][0]["reasoning"]


class TestSourceFailures:

    def test_failing_source_is_counted_and_run_still_completes(self, client, monkeypatch):
        def boom(keywords, limit=50, **options):
            raise SourceError("remotive: offline")

        monkeypatch.setattr(REGISTRY["remotive"], "fetch", boom)
        start(client, sources=["remotive", "remoteok"])
        status = wait_for(client, {"complete"})
        assert status["message"] == "complete"
        assert status["source_errors"] == 1
        assert status["added"] == 2

    def test_unknown_source_is_rejected_without_a_run(self, client):
        start(client, sources=["linkedin"])
        status = wait_for(client, {"invalid_sources"})
        assert status["message"] == "invalid_sources"
        assert status["running"] is False
        assert db.count_jobs() == 0

    def test_lock_is_released_after_invalid_sources(self, client):
        start(client, sources=["linkedin"])
        wait_for(client, {"invalid_sources"})
        assert scraper.is_running() is False
