import pytest

from jobsieve import cli, discovery, watchlist
from jobsieve.sources import ddg
from jobsieve.sources.base import JobRecord


@pytest.mark.parametrize("url,expected", [
    ("https://boards.greenhouse.io/careem/jobs/8873949002?gh_jid=1", ("greenhouse", "careem")),
    ("https://job-boards.greenhouse.io/acme", ("greenhouse", "acme")),
    ("https://boards.greenhouse.io/embed/job_board?for=widgetco", ("greenhouse", "widgetco")),
    ("https://jobs.lever.co/palantir/6ed76ce8", ("lever", "palantir")),
    ("https://jobs.ashbyhq.com/Ashby/7458", ("ashby", "Ashby")),
    ("https://jobs.smartrecruiters.com/Bosch/123-engineer", ("smartrecruiters", "Bosch")),
])
def test_company_is_read_from_board_urls(url, expected):
    assert discovery.board_from_url(url) == expected


@pytest.mark.parametrize("url", [
    "https://example.com/careem", "https://jobs.lever.co/", "https://boards.greenhouse.io/embed/job_board",
    "https://boards.greenhouse.io/api/x", "not a url", "", None, "https://jobs.lever.co/a b/x",
])
def test_other_urls_are_ignored(url):
    assert discovery.board_from_url(url) is None


def test_learn_adds_once_and_marks_as_discovered():
    urls = ["https://jobs.lever.co/acme/1", "https://jobs.lever.co/acme/2", "https://example.com/x"]
    assert discovery.learn(urls) == 1
    assert discovery.learn(urls) == 0
    assert watchlist.load() == [{"board": "lever", "slug": "acme", "added_by": "discovered"}]


def test_a_manual_entry_is_not_relabelled():
    watchlist.add("lever", "acme")
    discovery.learn(["https://jobs.lever.co/acme/1"])
    assert watchlist.load()[0]["added_by"] == "manual"


def test_search_queries_each_board_and_place(monkeypatch):
    queries = []

    def fake(self, site, keyword, limit=10):
        queries.append((site, keyword))
        return [JobRecord(title="t", company=site, url=f"https://{site}/co{len(queries)}/job", source="ddg")]

    monkeypatch.setattr(ddg.DdgSource, "search", fake)
    added = discovery.search(["engineer"], ["Dubai"], sites=["jobs.lever.co", "jobs.ashbyhq.com"])
    assert added == 2 and queries == [("jobs.lever.co", "engineer Dubai"), ("jobs.ashbyhq.com", "engineer Dubai")]


def test_discover_command(monkeypatch, capsys):
    monkeypatch.setattr(discovery, "search", lambda keywords, places: 3)
    monkeypatch.setenv("CONFIG_DIR", "x"); monkeypatch.setenv("DATA_DIR", __import__("os").environ["DATA_DIR"])
    assert cli.main(["discover", "--keyword", "engineer", "--place", "Dubai"]) == 0
    assert "3 new companies" in capsys.readouterr().out


def test_a_web_search_run_adds_the_companies_it_finds(monkeypatch):
    import time
    from fastapi.testclient import TestClient
    from jobsieve.api import api

    monkeypatch.setattr(
        ddg, "ddg_text",
        lambda query, max_results=10: [{"title": "Engineer", "href": "https://jobs.lever.co/acme/1", "body": "python"}],
    )
    client = TestClient(api)
    assert client.post("/run", json={"provider": "groq", "lite_mode": True, "sites": ["jobs.lever.co"],
                                     "keywords": ["python"], "cv_text": ""}).json()["started"] is True
    deadline = time.time() + 10
    while time.time() < deadline and client.get("/status").json().get("message") not in ("complete", "completed"):
        time.sleep(0.05)
    assert watchlist.load() == [{"board": "lever", "slug": "acme", "added_by": "discovered"}]
