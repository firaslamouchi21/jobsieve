import os
import sys

import pytest

from jobsieve import cli, db, demo, launcher
from jobsieve import profile as prof


class TestDemo:

    def test_seeds_a_profile_and_a_spread_of_verdicts(self):
        assert demo.seed() == len(demo.DEMO_JOBS)
        assert prof.exists() and prof.load()["home_country"] == "AE"
        jobs = db.list_jobs(limit=50)
        assert len(jobs) == len(demo.DEMO_JOBS)
        verdicts = {j["eligibility"] for j in jobs}
        assert "eligible" in verdicts and "not_eligible" in verdicts
        assert all(j["link"].startswith("https://example.com/demo/") for j in jobs)

    def test_seeding_twice_does_not_duplicate(self):
        demo.seed(); demo.seed()
        assert len(db.list_jobs(limit=50)) == len(demo.DEMO_JOBS)

    def test_the_clear_cases_come_out_right(self):
        demo.seed()
        by_title = {j["title"]: j["eligibility"] for j in db.list_jobs(limit=50)}
        assert by_title["Senior Data Engineer"] == "eligible"
        assert by_title["Data Platform Engineer"] == "not_eligible"
        assert by_title["Platform Engineer"] != "eligible"


class TestLauncher:

    def test_reports_missing_extras(self, monkeypatch, capsys):
        monkeypatch.setattr(launcher.importlib.util, "find_spec", lambda name: None)
        assert launcher.missing_extras() == ["api", "ui"]
        assert launcher.start() == 2
        assert 'jobsieve[api,ui]' in capsys.readouterr().err

    def test_starts_both_servers_and_stops_them(self, monkeypatch):
        started = []

        class Process:
            def __init__(self, cmd, env=None):
                started.append((cmd, env)); self.polled = 0; self.ended = False
            def poll(self):
                self.polled += 1
                return None if self.polled < 3 and not self.ended else 0
            def terminate(self): self.ended = True
            def wait(self, timeout=None): return 0
            def kill(self): pass

        monkeypatch.setattr(launcher.subprocess, "Popen", lambda cmd, env=None: Process(cmd, env))
        monkeypatch.setattr(launcher.time, "sleep", lambda s: None)
        monkeypatch.setattr(launcher, "missing_extras", lambda: [])
        assert launcher.start(9000, 9500, open_browser=False) == 0
        api, ui = started
        assert "uvicorn" in api[0] and "9000" in api[0] and "127.0.0.1" in api[0]
        assert "streamlit" in ui[0] and "9500" in ui[0] and api[1]["SCRAPER_URL"] == "http://127.0.0.1:9000"

    def test_cli_demo_uses_a_separate_folder(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("DATA_DIR", raising=False)
        seen = {}
        monkeypatch.setattr(launcher, "start", lambda *a: seen.setdefault("args", a) and 0)
        assert cli.main(["start", "--demo", "--no-browser"]) == 0
        assert os.environ["DATA_DIR"] == "./demo-data" and (tmp_path / "demo-data" / "jobs.sqlite").exists()
        assert seen["args"] == (8000, 8501, False)
