import json
import os
import subprocess
import sys
import time

import pytest
from fastapi.testclient import TestClient

from jobsieve.api import api
from jobsieve import scraper


def write_lock_file(pid, heartbeat):
    os.makedirs(scraper.data_dir(), exist_ok=True)
    with open(scraper.lock_path(), "w", encoding="utf-8") as f:
        json.dump({"pid": pid, "started_at": heartbeat, "heartbeat": heartbeat}, f)


def dead_pid():
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


@pytest.fixture
def client():
    return TestClient(api)


class TestLockContents:

    def test_lock_records_pid_and_timestamps(self):
        assert scraper.try_lock() is True
        try:
            data = scraper.read_lock()
            assert data["pid"] == os.getpid()
            assert data["started_at"] <= data["heartbeat"]
        finally:
            scraper.unlock()

    def test_live_lock_blocks_second_run(self):
        assert scraper.try_lock() is True
        try:
            assert scraper.try_lock() is False
            assert scraper.is_running() is True
        finally:
            scraper.unlock()

    def test_status_writes_refresh_heartbeat(self):
        assert scraper.try_lock() is True
        try:
            before = scraper.read_lock()["heartbeat"]
            time.sleep(0.02)
            scraper.write_status("running", 10, {"running": True})
            assert scraper.read_lock()["heartbeat"] > before
        finally:
            scraper.unlock()


class TestStaleLock:

    def test_dead_pid_lock_is_stale_and_replaced(self):
        write_lock_file(dead_pid(), time.time())
        assert scraper.lock_is_stale() is True
        assert scraper.is_running() is False
        assert scraper.try_lock() is True
        assert scraper.read_lock()["pid"] == os.getpid()
        scraper.unlock()

    def test_old_heartbeat_expires_even_if_pid_alive(self, monkeypatch):
        monkeypatch.setattr(scraper, "LOCK_STALE_SECONDS", 60)
        write_lock_file(os.getpid(), time.time() - 3600)
        assert scraper.lock_is_stale() is True
        assert scraper.try_lock() is True
        scraper.unlock()

    def test_fresh_heartbeat_with_live_pid_is_not_stale(self):
        write_lock_file(os.getpid(), time.time())
        assert scraper.lock_is_stale() is False
        assert scraper.try_lock() is False
        scraper.unlock()

    def test_unreadable_lock_file_expires_by_age(self, monkeypatch):
        monkeypatch.setattr(scraper, "LOCK_STALE_SECONDS", 60)
        os.makedirs(scraper.data_dir(), exist_ok=True)
        with open(scraper.lock_path(), "w", encoding="utf-8") as f:
            f.write("1700000000.0")
        old = time.time() - 3600
        os.utime(scraper.lock_path(), (old, old))
        assert scraper.lock_is_stale() is True

    def test_api_accepts_new_run_after_crash(self, client, monkeypatch):
        monkeypatch.setenv("MOCK_SEARCH", "true")
        write_lock_file(dead_pid(), time.time())
        payload = {
            "provider": "groq",
            "lite_mode": True,
            "sites": ["example.com"],
            "keywords": ["python"],
            "cv_text": "",
        }
        assert client.post("/run", json=payload).json() == {"started": True}
        deadline = time.time() + 10
        while time.time() < deadline:
            if client.get("/status").json().get("message") == "complete":
                break
            time.sleep(0.1)
        assert client.get("/status").json()["message"] == "complete"


class TestStartupRecovery:

    def test_startup_clears_lock_and_marks_run_interrupted(self):
        write_lock_file(os.getpid(), time.time())
        scraper.write_status("running", 40, {"running": True, "added": 3})
        write_lock_file(os.getpid(), time.time())
        with TestClient(api) as started:
            assert not os.path.exists(scraper.lock_path())
            data = started.get("/status").json()
            assert data["running"] is False
            assert data["message"] == "interrupted"
            assert data["added"] == 3

    def test_status_does_not_report_dead_run_as_running(self, client):
        scraper.write_status("running", 40, {"running": True})
        scraper.unlock()
        data = client.get("/status").json()
        assert data["running"] is False
        assert data["message"] == "interrupted"

    def test_pause_and_stop_ignore_dead_run(self, client):
        write_lock_file(dead_pid(), time.time())
        assert client.post("/pause").json()["running"] is False
        assert client.post("/stop").json()["running"] is False


class TestStatusFile:

    def test_status_write_is_atomic_and_leaves_no_temp_file(self):
        scraper.write_status("running", 10, {"running": False})
        names = os.listdir(scraper.data_dir())
        assert "status.json" in names
        assert "status.json.tmp" not in names
