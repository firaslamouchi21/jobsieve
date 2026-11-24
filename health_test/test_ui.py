import os

import pytest

pytest.importorskip("streamlit")

from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

import jobsieve
from jobsieve import db, demo
from jobsieve import profile as prof
from jobsieve.api import api
from jobsieve.sources.base import JobRecord
from jobsieve.ui import client, components

ROOT = os.path.dirname(jobsieve.__file__)


@pytest.fixture
def backend(monkeypatch):
    """The dashboard talks to the real API, in process."""
    server = TestClient(api)

    def request(method, url, json=None, params=None, headers=None, timeout=None):
        return server.request(method, url.replace(client.SCRAPER_URL, ""), json=json, params=params, headers=headers)

    monkeypatch.setattr(client.requests, "request", request)
    return server


def page(name):
    script = f"from jobsieve.ui import pages\npages.{name}()\n"
    return AppTest.from_string(script, default_timeout=30).run()


def clean(app):
    assert [e.value for e in app.exception] == []
    return app


def button(app, label):
    return next(b for b in app.button if b.label == label)


@pytest.mark.parametrize("name", ["jobs_page", "search_page", "profile_page", "watchlist_page"])
def test_every_page_renders_empty_and_with_data(backend, name):
    clean(page(name))
    demo.seed()
    clean(page(name))


@pytest.mark.parametrize("name", ["jobs_page", "search_page", "profile_page", "watchlist_page"])
def test_every_page_survives_the_api_being_down(monkeypatch, name):
    def down(*args, **kwargs):
        raise client.requests.ConnectionError()

    monkeypatch.setattr(client.requests, "request", down)
    app = clean(page(name))
    assert any("API" in e.value for e in app.error)


def test_the_app_shell_renders(backend):
    demo.seed()
    clean(AppTest.from_file(os.path.join(ROOT, "app.py"), default_timeout=30).run())


def test_saving_a_job_moves_it(backend):
    demo.seed()
    app = page("jobs_page")
    clean(button(app, "Save").click().run())
    assert db.summary("")["by_status"]["saved"] == 1


def test_search_sends_keywords_and_respects_lite_mode(backend, monkeypatch):
    prof.save({"keywords": ["python"], "cv_text": "cv"})
    sent = []
    real = client.call
    monkeypatch.setattr(client, "call", lambda m, p, *a, **k: (sent.append(a[0]), ({"started": True}, ""))[1] if p == "/run" else real(m, p, *a, **k))
    clean(button(page("search_page"), "Start search").click().run())
    assert sent[0]["keywords"] == ["python"] and sent[0]["lite_mode"] is True and sent[0]["groq_api_key"] == ""


def test_search_cannot_start_without_keywords(backend):
    assert button(page("search_page"), "Start search").disabled


def test_saving_the_profile_keeps_fields_the_form_does_not_show(backend):
    prof.save({"home_country": "AE", "languages": ["Arabic"], "sites": ["x.com"], "sources": ["remotive"]})
    clean(button(page("profile_page"), "Save profile").click().run())
    saved = prof.load()
    assert saved["languages"] == ["arabic"] and saved["sites"] == ["x.com"] and saved["sources"] == ["remotive"]


def test_listing_text_cannot_inject_markdown_or_unsafe_links():
    assert components.plain("**b** [x](javascript:1) :red[y] $z$") == r"\*\*b\*\* \[x\]\(javascript\:1\) \:red\[y\] \$z\$"
    assert components.safe_link("javascript:alert(1)") == "" and components.safe_link("https://x") == "https://x"


def test_summary_counts_and_visits(backend):
    db.init()
    for i, verdict in enumerate(("eligible", "unknown", None)):
        db.upsert_record(JobRecord(title=f"R{i}", company="A", url=f"https://x/{i}", source="lever", location="Dubai"), 5, "r", eligibility=verdict)
    db.set_meta("last_visit", "1970-01-01")
    body = backend.get("/summary").json()
    assert body["inbox_by_eligibility"] == {"eligible": 1, "unknown": 1, "unchecked": 1} and body["new_since_visit"] == 1
    backend.post("/visit")
    assert backend.get("/summary").json()["new_since_visit"] == 0


def test_the_docker_theme_matches_the_packaged_one():
    with open(os.path.join(ROOT, "data", ".streamlit", "config.toml")) as packaged, open(os.path.join(os.path.dirname(ROOT), ".streamlit", "config.toml")) as docker:
        assert packaged.read() == docker.read()
