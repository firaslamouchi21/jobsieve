from datetime import datetime, timedelta, timezone

import pytest

from jobsieve import db, freshness
from jobsieve.sources import boards
from jobsieve.sources.base import JobRecord

NOW = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)


def ago(days):
    return (NOW - timedelta(days=days)).isoformat()


@pytest.mark.parametrize("days,label", [(0, "new"), (3, "new"), (4, "recent"), (14, "recent"), (15, "old"), (45, "old"), (46, "stale")])
def test_age_labels(days, label):
    assert freshness.assess({"posted_at": ago(days)}, NOW)["label"] == label


def test_first_seen_is_used_when_there_is_no_posted_date():
    result = freshness.assess({"created_at": ago(40)}, NOW)
    assert result["label"] == "old" and result["facts"] == ["first seen 40 days ago"]


def test_nothing_known_is_unknown():
    assert freshness.assess({}, NOW) == {"label": "unknown", "facts": []}
    assert freshness.assess({"posted_at": "garbage"}, NOW)["label"] == "unknown"


def test_closed_by_source_or_by_stated_date():
    closed = freshness.assess({"posted_at": ago(1), "closed_at": ago(0)}, NOW)
    assert closed["label"] == "closed" and "no longer listed by its source" in closed["facts"]
    past = freshness.assess({"posted_at": ago(1), "expires_at": ago(1)}, NOW)
    assert past["label"] == "closed" and "past its stated closing date" in past["facts"]


def test_facts_state_closing_and_reposts_plainly():
    result = freshness.assess({"posted_at": ago(1), "expires_at": (NOW + timedelta(days=1, hours=3)).isoformat(), "repost_count": 2}, NOW)
    assert result["label"] == "new"
    assert "closes in 1 day" in result["facts"] and "reposted 2 times" in result["facts"]


def record(url="https://x/1", posted="2026-11-20T00:00:00+00:00", **kw):
    return JobRecord(title="Engineer", company="Acme", url=url, source="lever", location="Dubai", posted_at=posted, **kw)


class TestStorage:

    def test_expiry_and_freshness_come_back_with_the_job(self):
        db.init()
        db.upsert_record(record(expires_at="2999-01-01T00:00:00+00:00"), 5, "r")
        job = db.list_jobs()[0]
        assert job["expires_at"].startswith("2999") and job["freshness"]["label"] in ("new", "recent", "old", "stale")

    def test_expired_and_closed_jobs_are_hidden_unless_asked(self):
        db.init()
        db.upsert_record(record("https://x/old", expires_at="2020-01-01T00:00:00+00:00"), 5, "r")
        db.upsert_record(record("https://x/gone", posted="2026-11-21T00:00:00+00:00"), 5, "r")
        db.upsert_record(record("https://x/open", posted="2026-11-22T00:00:00+00:00"), 5, "r")
        assert db.mark_closed(["https://x/gone", "https://x/missing", ""]) == 1
        assert [j["link"] for j in db.list_jobs()] == ["https://x/open"]
        assert len(db.list_jobs(include_closed=True, include_duplicates=True)) == 3

    def test_seeing_a_closed_job_again_reopens_it(self):
        db.init()
        db.upsert_record(record(), 5, "r")
        db.mark_closed(["https://x/1"])
        db.upsert_record(record(), 5, "r")
        assert len(db.list_jobs()) == 1

    def test_a_later_posted_date_counts_as_a_repost(self):
        db.init()
        db.upsert_record(record(posted="2026-10-01T00:00:00+00:00"), 5, "r")
        db.upsert_record(record(posted="2026-10-01T00:00:00+00:00"), 5, "r")
        db.upsert_record(record(posted="2026-11-01T00:00:00+00:00"), 5, "r")
        assert db.list_jobs()[0]["repost_count"] == 1

    def test_order_is_eligibility_then_score_then_recency(self):
        db.init()
        for url, score, verdict, posted in [("a", 9, "unknown", "2026-11-20"), ("b", 3, "eligible", "2026-11-01"),
                                            ("c", 3, "eligible", "2026-11-20"), ("d", 9, "not_eligible", "2026-11-20")]:
            db.upsert_record(record(f"https://x/{url}", posted=posted), score, "r", eligibility=verdict)
        assert [j["link"][-1] for j in db.list_jobs()] == ["c", "b", "a", "d"]


class TestBoardsCloseJobs:

    def test_a_job_that_leaves_a_board_is_closed(self):
        db.init()
        a, b = record("https://x/a"), record("https://x/b")
        db.upsert_record(a, 5, "r"); db.upsert_record(b, 5, "r")
        boards.close_removed("lever", [a, b], [a])
        assert [j["link"] for j in db.list_jobs()] == ["https://x/a"]

    def test_a_full_smartrecruiters_page_is_not_trusted(self):
        db.init()
        a = record("https://x/a")
        db.upsert_record(a, 5, "r")
        boards.close_removed("smartrecruiters", [a], [record(f"https://x/{i}") for i in range(100)])
        assert len(db.list_jobs()) == 1

    def test_refreshing_a_cached_board_closes_removed_jobs(self, monkeypatch):
        from jobsieve import watchlist
        from jobsieve.sources import base, get_source

        monkeypatch.setenv("MOCK_SEARCH", "false")
        monkeypatch.setenv("SOURCE_CACHE_TTL_SECONDS", "0")
        monkeypatch.setattr(boards, "sleep_delay", lambda: None)
        db.init()
        watchlist.add("lever", "acme")
        payloads = [[{"text": "A", "hostedUrl": "https://x/a", "categories": {"location": "Dubai"}},
                     {"text": "B", "hostedUrl": "https://x/b", "categories": {"location": "Dubai"}}],
                    [{"text": "A", "hostedUrl": "https://x/a", "categories": {"location": "Dubai"}}]]
        monkeypatch.setattr(base, "fetch_json", lambda url: payloads.pop(0))
        for r in get_source("boards").fetch([]):
            db.upsert_record(r, 5, "r")
        get_source("boards").fetch([])
        assert [j["link"] for j in db.list_jobs()] == ["https://x/a"]

    def test_an_empty_refresh_closes_nothing(self, monkeypatch):
        from jobsieve.sources import base
        called = []
        monkeypatch.setenv("SOURCE_CACHE_TTL_SECONDS", "0")
        base.write_cache("t", [record()])
        base.load_feed("t", 0, lambda: [], on_removed=lambda *a: called.append(a))
        assert called == []


def test_csv_export_flattens_freshness_and_duplicates(monkeypatch):
    from fastapi.testclient import TestClient
    from jobsieve.api import api

    db.init()
    db.upsert_record(record(), 5, "r")
    text = TestClient(api).get("/export/csv").text
    header = text.splitlines()[0].split(",")
    assert "freshness" in header and "freshness_facts" in header
    assert "{'label'" not in text


def test_api_can_include_closed_jobs():
    from fastapi.testclient import TestClient
    from jobsieve.api import api

    db.init()
    db.upsert_record(record(), 5, "r")
    db.mark_closed(["https://x/1"])
    client = TestClient(api)
    assert client.get("/jobs").json()["jobs"] == []
    jobs = client.get("/jobs?include_closed=true").json()["jobs"]
    assert jobs[0]["freshness"]["label"] == "closed"
