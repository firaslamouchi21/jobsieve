from jobsieve import db, notifications


class TestMinScoreNotifyScale:

    def test_default_threshold_is_reachable_on_the_0_to_10_score_scale(self):
        assert 0 <= notifications.MIN_SCORE_NOTIFY <= 10

    def test_check_and_notify_fires_for_job_scoring_above_threshold(self, monkeypatch):
        db.init()
        sent = {}
        monkeypatch.setattr(
            notifications, "send_webhook", lambda jobs: sent.setdefault("webhook", jobs)
        )
        monkeypatch.setattr(
            notifications, "send_email", lambda jobs: sent.setdefault("email", jobs)
        )
        notifications.set_last_check("1970-01-01T00:00:00")
        db.upsert_job(
            title="Great match",
            company="a",
            link="https://example.com/a",
            site="a",
            snippet="",
            score=8,
            reasoning="",
        )
        db.upsert_job(
            title="Weak match",
            company="b",
            link="https://example.com/b",
            site="b",
            snippet="",
            score=2,
            reasoning="",
        )
        count = notifications.check_and_notify()
        assert count == 1
        assert [j["title"] for j in sent["webhook"]] == ["Great match"]
        assert [j["title"] for j in sent["email"]] == ["Great match"]

    def test_check_and_notify_does_not_fire_when_nothing_qualifies(self, monkeypatch):
        db.init()
        called = []
        monkeypatch.setattr(notifications, "send_webhook", lambda jobs: called.append(jobs))
        monkeypatch.setattr(notifications, "send_email", lambda jobs: called.append(jobs))
        notifications.set_last_check("1970-01-01T00:00:00")
        db.upsert_job(
            title="Weak match",
            company="a",
            link="https://example.com/a",
            site="a",
            snippet="",
            score=1,
            reasoning="",
        )
        count = notifications.check_and_notify()
        assert count == 0
        assert called == []


class FakeResponse:
    def __init__(self, status):
        self.status_code = status

    def raise_for_status(self):
        import requests

        if self.status_code >= 400:
            raise requests.HTTPError(f"http {self.status_code}")


def job(score=9):
    return {"title": "t", "score": score, "link": "https://example.com/t"}


class TestDeliveryFailures:

    def test_webhook_http_error_counts_as_failure(self, monkeypatch):
        monkeypatch.setattr(notifications, "NOTIFICATION_WEBHOOK", "https://hook.example")
        monkeypatch.setattr(notifications.requests, "post", lambda *a, **k: FakeResponse(500))
        assert notifications.send_webhook([job()]) is False

    def test_webhook_success(self, monkeypatch):
        monkeypatch.setattr(notifications, "NOTIFICATION_WEBHOOK", "https://hook.example")
        monkeypatch.setattr(notifications.requests, "post", lambda *a, **k: FakeResponse(204))
        assert notifications.send_webhook([job()]) is True

    def test_failed_delivery_does_not_advance_last_check(self, monkeypatch):
        db.init()
        monkeypatch.setattr(notifications, "NOTIFICATION_WEBHOOK", "https://hook.example")
        monkeypatch.setattr(notifications, "send_webhook", lambda jobs: False)
        monkeypatch.setattr(notifications, "send_email", lambda jobs: False)
        notifications.set_last_check("1970-01-01T00:00:00")
        db.upsert_job("Great", "a", "https://example.com/a", "a", "", 9, "")
        notifications.check_and_notify()
        assert notifications.get_last_check() == "1970-01-01T00:00:00"

    def test_successful_delivery_advances_last_check(self, monkeypatch):
        db.init()
        monkeypatch.setattr(notifications, "NOTIFICATION_WEBHOOK", "https://hook.example")
        monkeypatch.setattr(notifications, "send_webhook", lambda jobs: True)
        monkeypatch.setattr(notifications, "send_email", lambda jobs: False)
        notifications.set_last_check("1970-01-01T00:00:00")
        db.upsert_job("Great", "a", "https://example.com/a", "a", "", 9, "")
        notifications.check_and_notify()
        assert notifications.get_last_check() > "1970-01-01T00:00:00"

    def test_unconfigured_alerts_still_advance_last_check(self, monkeypatch):
        db.init()
        monkeypatch.setattr(notifications, "NOTIFICATION_WEBHOOK", "")
        monkeypatch.setattr(notifications, "EMAIL_HOST", "")
        notifications.set_last_check("1970-01-01T00:00:00")
        db.upsert_job("Great", "a", "https://example.com/a", "a", "", 9, "")
        notifications.check_and_notify()
        assert notifications.get_last_check() > "1970-01-01T00:00:00"
