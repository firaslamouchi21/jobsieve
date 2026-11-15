import json
import os

from jobsieve import cli, db, scraper


def run_cli(*extra):
    return cli.main(["run", "--lite", *extra])


class TestRunCommand:

    def test_run_with_flags_stores_jobs(self, capsys):
        code = run_cli("--sites", "example.com", "--keywords", "python")
        assert code == 0
        assert db.count_jobs() == 1

    def test_run_without_keywords_exits_cleanly(self):
        assert run_cli("--sites", "example.com") == 0
        assert db.count_jobs() == 0

    def test_cv_file_is_used(self, tmp_path):
        cv = tmp_path / "cv.txt"
        cv.write_text("python django postgresql docker kubernetes aws redis")
        code = run_cli("--sites", "example.com", "--keywords", "python", "--cv-file", str(cv))
        assert code == 0
        assert "cv_terms=" in db.list_jobs()[0]["reasoning"]

    def test_missing_cv_file_is_an_error(self, capsys):
        code = run_cli("--keywords", "python", "--cv-file", "/no/such/file.txt")
        assert code == 2
        assert "cannot read CV file" in capsys.readouterr().err

    def test_second_run_while_locked_says_so_and_fails(self, capsys):
        db.init()
        assert scraper.try_lock() is True
        try:
            code = run_cli("--sites", "example.com", "--keywords", "python")
        finally:
            scraper.unlock()
        assert code == 1
        assert "already in progress" in capsys.readouterr().err
        assert db.count_jobs() == 0

    def test_lock_is_released_after_run(self):
        run_cli("--sites", "example.com", "--keywords", "python")
        assert not os.path.exists(scraper.lock_path())


class TestExportCommand:

    def test_export_json_is_valid(self, capsys):
        db.init()
        db.upsert_job("t", "c", "https://example.com/x", "c", "s", 5, "r")
        assert cli.main(["export", "--format", "json"]) == 0
        rows = json.loads(capsys.readouterr().out)
        assert rows[0]["title"] == "t"
