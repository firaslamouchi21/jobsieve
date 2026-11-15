import json

import pytest
from fastapi.testclient import TestClient

from jobsieve import db, eligibility, scraper
from jobsieve import profile as prof
from jobsieve.api import api
from jobsieve.sources import REGISTRY
from jobsieve.sources.base import JobRecord


def run(sources=("remoteok",), keywords=("python",)):
    scraper.run_scrape("", True, sources=list(sources), keywords=list(keywords), sites=["example.com"], cv_text="")


def rows():
    return {j["title"]: j for j in db.list_jobs(limit=50)}


class TestVerdictsAreStored:

    def test_without_a_profile_nothing_is_judged(self):
        run()
        assert all(j["eligibility"] is None for j in db.list_jobs())

    def test_with_a_profile_every_job_gets_a_verdict_and_reasons(self):
        prof.save({"home_country": "AE", "work_authorization": ["GCC"]})
        run()
        jobs = db.list_jobs()
        assert jobs and all(j["eligibility"] in ("eligible", "not_eligible", "unknown") for j in jobs)
        assert all(isinstance(j["eligibility_reasons"], list) and j["eligibility_reasons"] for j in jobs)
        assert all(j["profile_fingerprint"] for j in jobs)

    def test_restricted_feed_job_is_filtered_for_the_wrong_country(self, monkeypatch):
        records = [
            JobRecord(title="US Python Dev", company="A", url="https://x.com/1", source="remotive", remote=True,
                      location="USA Only", restrictions="USA Only", description="python"),
            JobRecord(title="Global Python Dev", company="B", url="https://x.com/2", source="remotive", remote=True,
                      location="Worldwide", restrictions="Worldwide", description="python"),
        ]
        monkeypatch.setattr(REGISTRY["remotive"], "fetch", lambda keywords, limit=50, **o: records)
        prof.save({"home_country": "AE", "work_authorization": ["GCC"]})
        run(sources=["remotive"])
        found = rows()
        assert found["US Python Dev"]["eligibility"] == "not_eligible"
        assert found["Global Python Dev"]["eligibility"] == "eligible"
        assert found["US Python Dev"]["restrictions"] == "USA Only"

    def test_salary_and_seniority_are_stored(self, monkeypatch):
        records = [JobRecord(title="Senior Python Dev", company="A", url="https://x.com/1", source="remotive",
                             remote=True, restrictions="Worldwide", salary="$80k - $120k", description="python")]
        monkeypatch.setattr(REGISTRY["remotive"], "fetch", lambda keywords, limit=50, **o: records)
        prof.save({"home_country": "AE"})
        run(sources=["remotive"])
        job = db.list_jobs()[0]
        assert (job["seniority"], job["salary_min"], job["salary_max"], job["salary_currency"]) == ("senior", 80000, 120000, "USD")


class TestProfileFeedsTheRun:

    def test_keywords_cv_and_sources_default_from_the_profile(self):
        prof.save({"home_country": "AE", "keywords": ["python"], "sources": ["remoteok"],
                   "cv_text": "python developer backend remote mock listing"})
        scraper.run_scrape("", True)
        jobs = db.list_jobs()
        assert jobs and all(j["source"] == "remoteok" for j in jobs)
        assert "cv_terms=" in jobs[0]["reasoning"]

    def test_explicit_arguments_beat_the_profile(self):
        prof.save({"keywords": ["cobol"], "sources": ["remotive"]})
        scraper.run_scrape("", True, keywords=["python"], sources=["remoteok"])
        assert {j["source"] for j in db.list_jobs()} == {"remoteok"}

    def test_unreadable_profile_does_not_crash_a_run(self):
        with open(prof.profile_path(), "w") as f:
            f.write("{broken")
        run()
        assert db.count_jobs() == 2


class TestReevaluation:

    def test_changing_the_profile_updates_stored_verdicts_without_refetching(self):
        prof.save({"home_country": "AE", "work_authorization": ["GCC"], "dealbreakers": ["python"]})
        run()
        assert {j["eligibility"] for j in db.list_jobs()} == {"not_eligible"}
        updated = prof.save({"home_country": "AE", "work_authorization": ["GCC"], "dealbreakers": []})
        counts = eligibility.reevaluate_stored(updated)
        assert sum(counts.values()) == 2
        assert {j["eligibility"] for j in db.list_jobs()} <= {"eligible", "unknown"}
        assert {j["profile_fingerprint"] for j in db.list_jobs()} == {prof.fingerprint(updated)}


class TestFilters:

    def seed(self):
        db.init()
        for title, verdict in (("A", "eligible"), ("B", "not_eligible"), ("C", "unknown"), ("D", None)):
            db.upsert_job(title, "c", f"https://x.com/{title}", "s", "", 5, "", eligibility=verdict)

    def titles(self, **kw):
        return sorted(j["title"] for j in db.list_jobs(**kw))

    def test_filter_by_verdict(self):
        self.seed()
        assert self.titles(eligibility=["eligible"]) == ["A"]
        assert self.titles(eligibility=["eligible", "unknown"]) == ["A", "C"]
        assert self.titles(eligibility=["not_eligible"]) == ["B"]
        assert self.titles(eligibility=["unchecked"]) == ["D"]
        assert self.titles() == ["A", "B", "C", "D"]

    def test_unknown_filter_values_match_nothing_instead_of_everything(self):
        self.seed()
        assert self.titles(eligibility=["bogus"]) == []

    def test_reasons_come_back_as_a_list(self):
        db.init()
        db.upsert_job("A", "c", "https://x.com/a", "s", "", 5, "", eligibility="eligible", eligibility_reasons=["why"])
        assert db.list_jobs()[0]["eligibility_reasons"] == ["why"]


class TestSchemaV3:

    def test_older_database_is_migrated_and_keeps_its_jobs(self):
        import sqlite3

        db.init()
        db.upsert_job("Old", "c", "https://x.com/old", "s", "", 5, "r")
        conn = sqlite3.connect(db.db_path())
        conn.execute("PRAGMA user_version = 2")
        conn.commit()
        conn.close()
        db.init()
        job = db.list_jobs()[0]
        assert job["title"] == "Old" and job["eligibility"] is None
