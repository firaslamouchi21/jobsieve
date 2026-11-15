import time

from jobsieve import db


class TestListJobsOrdering:

    def test_higher_score_ranks_first_regardless_of_recency(self):
        db.init()
        db.upsert_job(
            title="Old but great match",
            company="a",
            link="https://example.com/a",
            site="a",
            snippet="",
            score=9,
            reasoning="",
        )
        db.upsert_job(
            title="Newer but weak match",
            company="b",
            link="https://example.com/b",
            site="b",
            snippet="",
            score=2,
            reasoning="",
        )
        jobs = db.list_jobs(limit=10)
        assert [j["title"] for j in jobs] == [
            "Old but great match",
            "Newer but weak match",
        ]

    def test_ties_broken_by_recency(self):
        db.init()
        db.upsert_job(
            title="First",
            company="a",
            link="https://example.com/a",
            site="a",
            snippet="",
            score=5,
            reasoning="",
        )
        time.sleep(0.01)
        db.upsert_job(
            title="Second",
            company="b",
            link="https://example.com/b",
            site="b",
            snippet="",
            score=5,
            reasoning="",
        )
        jobs = db.list_jobs(limit=10)
        titles = [j["title"] for j in jobs]
        assert titles[0] == "Second"
        assert set(titles) == {"First", "Second"}


def old_schema_database():
    import sqlite3

    conn = sqlite3.connect(db.db_path())
    conn.execute(
        "CREATE TABLE jobs ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, job_hash TEXT UNIQUE, "
        "title TEXT, company TEXT, link TEXT, site TEXT, "
        "snippet TEXT, score INTEGER, reasoning TEXT, created_at TEXT)"
    )
    conn.execute(
        "INSERT INTO jobs (job_hash, title, company, link, site, snippet, score, reasoning, created_at) "
        "VALUES (?, 'Old job', 'a', 'https://example.com/old', 'a', 's', 5, 'r', '2025-01-01T00:00:00+00:00')",
        (db.job_hash("Old job", "a", "https://example.com/old"),),
    )
    conn.commit()
    conn.close()


def add(title, score, reasoning="", run_id=None, link=None):
    return db.upsert_job(
        title=title,
        company="a",
        link=link or f"https://example.com/{title}",
        site="a",
        snippet="",
        score=score,
        reasoning=reasoning,
        run_id=run_id,
    )


class TestRescoring:

    def test_second_upsert_updates_score_and_reasoning(self):
        db.init()
        assert add("job", 2, "first") != ""
        assert add("job", 8, "second") == ""
        job = db.list_jobs()[0]
        assert (job["score"], job["reasoning"]) == (8, "second")
        assert db.count_jobs() == 1

    def test_ai_failure_does_not_overwrite_good_score(self):
        db.init()
        add("job", 9, "great fit")
        add("job", 1, "ai_failed: http 429 | matched_keywords=1")
        job = db.list_jobs()[0]
        assert (job["score"], job["reasoning"]) == (9, "great fit")

    def test_ai_failure_is_stored_when_nothing_better_exists(self):
        db.init()
        add("job", 0, "matched_keywords=0")
        add("job", 1, "ai_failed: timeout | matched_keywords=1")
        assert db.list_jobs()[0]["reasoning"].startswith("ai_failed:")

    def test_last_seen_advances_on_rerun(self):
        db.init()
        add("job", 5, "x")
        before = db.list_jobs()[0]["last_seen"]
        time.sleep(0.01)
        add("job", 5, "x")
        assert db.list_jobs()[0]["last_seen"] > before


class TestRuns:

    def test_latest_run_filter_returns_only_that_runs_jobs(self):
        db.init()
        first = db.start_run()
        add("seen-in-first", 9, run_id=first)
        time.sleep(0.01)
        second = db.start_run()
        add("seen-in-second", 3, run_id=second)
        assert db.latest_run_id() == second
        titles = [j["title"] for j in db.list_jobs(run_id=second)]
        assert titles == ["seen-in-second"]
        assert len(db.list_jobs()) == 2

    def test_rerun_moves_job_into_latest_run(self):
        db.init()
        first = db.start_run()
        add("job", 4, run_id=first)
        time.sleep(0.01)
        second = db.start_run()
        add("job", 6, run_id=second)
        assert [j["score"] for j in db.list_jobs(run_id=second)] == [6]
        assert db.list_jobs(run_id=first) == []

    def test_limit_is_clamped(self):
        db.init()
        add("job", 1)
        assert len(db.list_jobs(limit=-5)) == 1
        assert len(db.list_jobs(limit=10**9)) == 1


class TestMigration:

    def test_existing_database_is_migrated_and_keeps_rows(self):
        old_schema_database()
        db.init()
        jobs = db.list_jobs()
        assert [j["title"] for j in jobs] == ["Old job"]
        assert jobs[0]["last_seen"] == "2025-01-01T00:00:00+00:00"
        assert jobs[0]["run_id"] is None

    def test_migration_is_idempotent(self):
        old_schema_database()
        db.init()
        db.init()
        assert db.count_jobs() == 1

    def test_migrated_database_accepts_rescoring(self):
        old_schema_database()
        db.init()
        db.upsert_job("Old job", "a", "https://example.com/old", "a", "s", 9, "new", run_id="r")
        assert db.count_jobs() == 1


class TestUrlDedupe:

    def test_same_url_from_different_titles_and_sites_is_one_job(self):
        db.init()
        db.upsert_job("Dev", "a", "https://example.com/j/1", "a", "", 3, "x")
        again = db.upsert_job("Dev (new)", "b", "HTTPS://Example.com/j/1/?utm_source=z", "b", "", 6, "y")
        assert again == ""
        assert db.count_jobs() == 1
        assert db.list_jobs()[0]["score"] == 6

    def test_jobs_without_a_url_fall_back_to_title_and_site(self):
        db.init()
        db.upsert_job("Dev", "a", "", "a", "", 1, "")
        db.upsert_job("Dev", "a", "", "a", "", 2, "")
        db.upsert_job("Other", "a", "", "a", "", 2, "")
        assert db.count_jobs() == 2


class TestJobDetails:

    def test_details_are_stored(self):
        db.init()
        db.upsert_job(
            "Dev", "Acme", "https://example.com/1", "remoteok", "snip", 5, "r",
            source="remoteok", location="Berlin", remote=True,
            salary="80000-120000", posted_at="2026-11-11T00:00:00+00:00",
            description="Full text",
        )
        job = db.list_jobs()[0]
        assert job["source"] == "remoteok"
        assert job["location"] == "Berlin"
        assert job["remote"] == 1
        assert job["salary"] == "80000-120000"
        assert job["description"] == "Full text"

    def test_remote_false_is_kept_distinct_from_unknown(self):
        db.init()
        db.upsert_job("A", "c", "https://example.com/a", "s", "", 1, "", remote=False)
        db.upsert_job("B", "c", "https://example.com/b", "s", "", 1, "")
        by_title = {j["title"]: j["remote"] for j in db.list_jobs()}
        assert by_title == {"A": 0, "B": None}

    def test_rerun_without_details_keeps_earlier_details(self):
        db.init()
        db.upsert_job("A", "c", "https://example.com/a", "s", "", 1, "", location="Paris")
        db.upsert_job("A", "c", "https://example.com/a", "s", "", 2, "")
        assert db.list_jobs()[0]["location"] == "Paris"


class TestSetScore:

    def test_agent_can_write_score_and_reasons(self):
        db.init()
        h = db.upsert_job("A", "c", "https://example.com/a", "s", "", None, "")
        assert db.set_score(h, 9, "strong match on python and remote") is True
        job = db.list_jobs()[0]
        assert (job["score"], job["reasoning"]) == (9, "strong match on python and remote")

    def test_score_is_clamped_and_unknown_hash_reports_false(self):
        db.init()
        h = db.upsert_job("A", "c", "https://example.com/a", "s", "", 1, "")
        db.set_score(h, 99, "x")
        assert db.list_jobs()[0]["score"] == 10
        assert db.set_score("nope", 5, "x") is False

    def test_unscored_job_does_not_break_notifications(self, monkeypatch):
        from jobsieve import notifications

        db.init()
        db.upsert_job("A", "c", "https://example.com/a", "s", "", None, "")
        notifications.set_last_check("1970-01-01T00:00:00")
        assert notifications.check_and_notify() == 0


class TestMigrationToV2:

    def test_v1_database_gains_columns_and_merges_url_duplicates(self):
        import sqlite3

        conn = sqlite3.connect(db.db_path())
        conn.execute(
            "CREATE TABLE jobs (id INTEGER PRIMARY KEY AUTOINCREMENT, job_hash TEXT UNIQUE, "
            "title TEXT, company TEXT, link TEXT, site TEXT, snippet TEXT, score INTEGER, "
            "reasoning TEXT, created_at TEXT)"
        )
        rows = [
            ("h1", "Dev", "https://example.com/j/1", "a", 5, "2025-01-01T00:00:00+00:00"),
            ("h2", "Dev again", "https://example.com/j/1/", "b", 7, "2025-02-01T00:00:00+00:00"),
            ("h3", "Other", "https://example.com/j/2", "a", 3, "2025-01-01T00:00:00+00:00"),
        ]
        for h, title, link, site, score, created in rows:
            conn.execute(
                "INSERT INTO jobs (job_hash, title, company, link, site, snippet, score, reasoning, created_at) "
                "VALUES (?, ?, 'c', ?, ?, 's', ?, 'r', ?)",
                (h, title, link, site, score, created),
            )
        conn.commit()
        conn.close()
        db.init()
        jobs = {j["link"]: j for j in db.list_jobs()}
        assert len(jobs) == 2
        assert jobs["https://example.com/j/1/"]["score"] == 7
        assert all(j["source"] == "ddg" for j in jobs.values())
        assert db.upsert_job("x", "c", "https://example.com/j/2/", "a", "", 9, "") == ""
        assert db.count_jobs() == 2
