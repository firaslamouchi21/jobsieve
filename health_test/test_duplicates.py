import json

import pytest

from jobsieve import db, duplicates
from jobsieve.sources.base import JobRecord


def record(source, url, company="Careem", title="Account Manager I", location="Dubai, UAE", description="text"):
    return JobRecord(title=title, company=company, url=url, source=source, location=location, description=description)


def store(*records):
    db.init()
    for r in records:
        db.upsert_record(r, 5, "r", None)
    db.mark_duplicates()


def visible():
    return {j["source"]: j for j in db.list_jobs()}


class TestKey:

    def test_ignores_case_punctuation_and_legal_suffixes(self):
        a = duplicates.duplicate_key("Careem Inc.", "Account Manager I", "Dubai, United Arab Emirates", "lever")
        b = duplicates.duplicate_key("careem", "account  manager i", "Dubai", "remotive")
        assert a == b

    @pytest.mark.parametrize("args", [
        ("", "Title", "Dubai", "lever"), ("Acme", "", "Dubai", "lever"),
        ("Acme", "Title", "", "lever"), ("jobs.lever.co", "Title", "Dubai", "ddg"),
    ])
    def test_no_key_when_unsure(self, args):
        assert duplicates.duplicate_key(*args) is None

    def test_different_places_are_different_jobs(self):
        assert duplicates.duplicate_key("A", "T", "Dubai", "x") != duplicates.duplicate_key("A", "T", "Riyadh", "x")


class TestMarking:

    def test_company_board_copy_wins_and_lists_the_other(self):
        store(record("remotive", "https://r/1", description="longer description " * 20), record("greenhouse", "https://g/1"))
        shown = db.list_jobs()
        assert [j["source"] for j in shown] == ["greenhouse"]
        assert shown[0]["also_seen"] == [{"source": "remotive", "url": "https://r/1"}]
        assert len(db.list_jobs(include_duplicates=True)) == 2

    def test_without_a_board_copy_the_fuller_description_wins(self):
        store(record("remotive", "https://r/1", description="short"), record("arbeitnow", "https://a/1", description="much longer text here"))
        assert list(visible()) == ["arbeitnow"]

    def test_is_recomputed_not_sticky(self):
        store(record("remotive", "https://r/1"), record("greenhouse", "https://g/1"))
        store(record("lever", "https://l/1", title="Other Role"))
        assert len(db.list_jobs()) == 2

    def test_different_locations_stay_separate(self):
        store(record("remotive", "https://r/1", location="Dubai"), record("greenhouse", "https://g/1", location="Riyadh"))
        assert len(db.list_jobs()) == 2

    def test_run_view_keeps_the_job_when_only_its_duplicate_was_seen(self):
        db.init()
        db.upsert_record(record("greenhouse", "https://g/1"), 5, "r", "old-run")
        db.upsert_record(record("remotive", "https://r/1"), 5, "r", "new-run")
        db.mark_duplicates()
        assert [j["source"] for j in db.list_jobs(run_id="new-run")] == ["greenhouse"]


def test_migration_adds_the_duplicate_columns():
    db.init()
    conn = db.connect()
    assert {"duplicate_of", "also_seen"} <= db.table_columns(conn.cursor(), "jobs")
    assert conn.execute("PRAGMA user_version").fetchone()[0] == len(db.MIGRATIONS)
