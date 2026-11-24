import threading

import pytest

from jobsieve import cli, db, notifications, schedule, scraper, watchlist
from jobsieve.sources.base import JobRecord


class TestInterval:

    @pytest.mark.parametrize("value,seconds", [("6", 21600), ("0.5", 1800), ("0.01", 900), ("0", 0), ("", 0), (None, 0), ("x", 0), ("-3", 0)])
    def test_values(self, value, seconds):
        assert schedule.interval_seconds(value) == seconds


class TestRunOnce:

    def test_uses_lite_without_a_key_and_ai_with_one(self, monkeypatch):
        calls = []
        monkeypatch.setattr(scraper, "run_scrape", lambda *a, **k: (calls.append((a, k)), scraper.unlock()))
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        assert schedule.run_once() is True and calls[-1][0][1] is True
        monkeypatch.setenv("GROQ_API_KEY", "k")
        schedule.run_once()
        assert calls[-1][0][1] is False and calls[-1][1]["_lock_acquired"] is True

    def test_skips_when_a_run_is_already_going(self, monkeypatch):
        assert scraper.try_lock()
        monkeypatch.setattr(scraper, "run_scrape", lambda *a, **k: pytest.fail("ran"))
        assert schedule.run_once() is False
        scraper.unlock()

    def test_loop_runs_until_stopped_and_survives_errors(self, monkeypatch):
        stop, count = threading.Event(), []

        def once():
            count.append(1)
            if len(count) == 1:
                raise RuntimeError("boom")
            stop.set()

        monkeypatch.setattr(schedule, "run_once", once)
        monkeypatch.setattr(schedule, "interval_seconds", lambda h: 0.01)
        schedule.loop(1, stop)
        assert len(count) == 2

    def test_environment_starts_a_thread_only_when_set(self, monkeypatch):
        monkeypatch.delenv("RUN_EVERY_HOURS", raising=False)
        assert schedule.start_from_environment() is None
        monkeypatch.setenv("RUN_EVERY_HOURS", "6")
        monkeypatch.setattr(schedule, "loop", lambda hours, stop=None: None)
        assert schedule.start_from_environment() is not None


class TestDefaultSources:

    def test_boards_and_pages_join_the_default_only_when_listed(self):
        assert scraper.default_source_names() == ["ddg"]
        watchlist.add("lever", "acme")
        watchlist.add_page("https://acme.com/careers")
        assert scraper.default_source_names() == ["ddg", "boards", "web"]


class TestDigest:

    def job(self, url, score, eligibility=None):
        db.init()
        db.upsert_record(JobRecord(title=f"Role {url[-1]}", company="Acme", url=url, source="lever", location="Dubai"),
                         score, "r", eligibility=eligibility)

    def test_markdown_lists_verdicts_and_counts(self):
        self.job("https://x/1", 9, "eligible"); self.job("https://x/2", 8, "unknown")
        text = notifications.render_markdown(notifications.pending_matches())
        assert "2 new matches" in text and "eligible" in text and "unclear" in text and "https://x/1" in text

    def test_digest_command_shows_without_moving_the_marker(self, capsys):
        self.job("https://x/1", 9)
        cli.main(["digest"]); cli.main(["digest"])
        assert capsys.readouterr().out.count("1 new matches") == 2

    def test_send_needs_a_channel_then_advances(self, monkeypatch, capsys):
        self.job("https://x/1", 9)
        monkeypatch.setattr(notifications, "NOTIFICATION_WEBHOOK", "")
        assert cli.main(["digest", "--send"]) == 2
        monkeypatch.setattr(notifications, "NOTIFICATION_WEBHOOK", "https://hook.example/x")
        monkeypatch.setattr(notifications, "send_webhook", lambda jobs: True)
        assert cli.main(["digest", "--send"]) == 0
        assert notifications.pending_matches() == []

    @pytest.mark.parametrize("url,key", [("https://hooks.slack.com/services/x", "text"), ("https://discord.com/api/webhooks/1/x", "content"),
                                         ("https://example.com/hook", "jobs")])
    def test_webhook_shape_follows_the_service(self, url, key):
        payload = notifications.webhook_payload(url, [{"title": "t", "link": "l", "score": 9, "location": "x"}])
        assert key in payload

    def test_telegram(self, monkeypatch):
        sent = []
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "T"); monkeypatch.setenv("TELEGRAM_CHAT_ID", "C")
        monkeypatch.setattr(notifications.requests, "post", lambda url, **k: (sent.append((url, k["json"])), type("R", (), {"raise_for_status": lambda self: None})())[1])
        assert notifications.send_telegram([{"title": "t", "link": "l", "score": 9}]) is True
        assert sent[0][0].endswith("botT/sendMessage") and sent[0][1]["chat_id"] == "C" and "**" not in sent[0][1]["text"]
        monkeypatch.delenv("TELEGRAM_CHAT_ID")
        assert notifications.send_telegram([]) is False


class TestLastVisit:

    def test_counts_only_new_eligible_unseen_jobs(self):
        db.init()
        for i, (verdict, status) in enumerate([("eligible", None), ("eligible", "hidden"), ("unknown", None)]):
            r = JobRecord(title=f"R{i}", company="A", url=f"https://x/{i}", source="lever", location="Dubai")
            db.upsert_record(r, 5, "r", eligibility=verdict)
            if status:
                db.set_status(db.record_hash(r), status)
        assert db.count_new_since("1970-01-01") == 1
        db.set_meta("last_visit", "2999-01-01")
        assert db.get_meta("last_visit") == "2999-01-01" and db.count_new_since("2999-01-01") == 0
