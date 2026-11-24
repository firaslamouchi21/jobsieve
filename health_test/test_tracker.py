import json

import pytest
from fastapi.testclient import TestClient

from jobsieve import cli, db, notifications
from jobsieve.api import api
from jobsieve.sources.base import JobRecord


def add(url="https://x/1", title="Engineer", company="Acme", score=8, **kw):
    db.init()
    record = JobRecord(title=title, company=company, url=url, source="lever", location="Dubai", **kw)
    db.upsert_record(record, score, "r")
    return db.record_hash(record)


@pytest.fixture
def client():
    return TestClient(api)


class TestStatus:

    def test_new_by_default_and_changes_are_logged(self):
        h = add()
        assert db.list_jobs()[0]["status"] == "new"
        assert db.set_status(h, "saved")["status"] == "saved"
        db.set_status(h, "saved")
        db.set_status(h, "applied", "sent CV")
        job = db.set_status(h, notes="call Monday")
        assert (job["status"], job["notes"]) == ("applied", "call Monday")
        assert db.event_counts("1970-01-01") == {"saved": 1, "applied": 1}

    def test_bad_status_unknown_job_and_long_note(self):
        h = add()
        with pytest.raises(ValueError):
            db.set_status(h, "maybe")
        with pytest.raises(ValueError):
            db.set_status(h, notes="x" * 2001)
        with pytest.raises(db.JobNotFound):
            db.set_status("nope", "saved")

    def test_hidden_jobs_stay_hidden_when_seen_again(self):
        h = add()
        db.set_status(h, "hidden")
        add()
        assert db.list_jobs() == []
        assert db.list_jobs(status=["hidden"])[0]["job_hash"] == h

    def test_status_survives_a_rescore(self):
        h = add()
        db.set_status(h, "applied", "n")
        add(score=2)
        job = db.list_jobs()[0]
        assert job["status"] == "applied" and job["notes"] == "n" and job["score"] == 2

    def test_filter_by_several_statuses(self):
        a, b, c = add("https://x/a"), add("https://x/b"), add("https://x/c")
        db.set_status(a, "applied"); db.set_status(b, "offer")
        assert {j["job_hash"] for j in db.list_jobs(status=["applied", "offer"])} == {a, b}
        assert [j["job_hash"] for j in db.list_jobs(status=["new"])] == [c]

    def test_find_hashes_needs_a_real_prefix(self):
        h = add()
        assert db.find_hashes(h[:8]) == [h]
        assert db.find_hashes(h[:3]) == [] and db.find_hashes("") == [] and db.find_hashes("zzzzzzzz") == []


class TestAlerts:

    def test_applied_hidden_and_ineligible_jobs_are_not_alerted(self):
        new, applied, hidden, blocked = add("https://x/n"), add("https://x/a"), add("https://x/h"), add("https://x/b")
        db.set_status(applied, "applied"); db.set_status(hidden, "hidden")
        db.upsert_record(JobRecord(title="Engineer", company="Acme", url="https://x/b", source="lever", location="Dubai"),
                         8, "r", eligibility="not_eligible")
        assert [j["job_hash"] for j in db.get_jobs_since("1970-01-01")] == [new]


class TestApiAndCli:

    def test_patch_get_and_stats(self, client):
        h = add()
        r = client.patch(f"/jobs/{h}", json={"status": "applied", "notes": "hi"})
        assert r.status_code == 200 and r.json()["job"]["status"] == "applied"
        assert client.get("/jobs").json()["jobs"][0]["notes"] == "hi"
        assert client.get("/jobs?status=saved").json()["jobs"] == []
        assert client.get("/stats").json()["changes"] == {"applied": 1}

    @pytest.mark.parametrize("body,code", [({"status": "maybe"}, 422), ({"notes": "x" * 2001}, 422)])
    def test_rejects_bad_input(self, client, body, code):
        assert client.patch(f"/jobs/{add()}", json=body).status_code == code

    def test_unknown_job_404_and_token(self, client, monkeypatch):
        assert client.patch("/jobs/nope", json={"status": "saved"}).status_code == 404
        monkeypatch.setenv("API_TOKEN", "t")
        assert client.patch("/jobs/nope", json={"status": "saved"}).status_code == 401

    def test_cli_mark_and_jobs(self, capsys):
        h = add(title="Backend Engineer")
        assert cli.main(["mark", h[:10], "saved", "--note", "n"]) == 0
        cli.main(["jobs", "--status", "saved"])
        assert "Backend Engineer" in capsys.readouterr().out
        assert cli.main(["mark", "zzzzzzzzzz", "saved"]) == 2

    def test_export_has_status_and_is_safe_for_spreadsheets(self, client):
        add(title="=HYPERLINK(\"http://evil\")", company="+cmd")
        text = client.get("/export/csv").text
        assert "status" in text.splitlines()[0]
        assert "'=HYPERLINK" in text and ",+cmd" not in text and "'+cmd" in text
