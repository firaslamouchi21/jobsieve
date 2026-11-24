import json

import pytest
from fastapi.testclient import TestClient

from jobsieve import cli, db
from jobsieve import profile as prof
from jobsieve.api import api


@pytest.fixture
def client():
    return TestClient(api)


class TestProfileApi:

    def test_get_before_anything_is_saved(self, client):
        data = client.get("/profile").json()
        assert data["exists"] is False and data["profile"]["home_country"] == ""

    def test_put_saves_and_returns_the_cleaned_profile(self, client):
        r = client.put("/profile", json={"home_country": "Saudi Arabia", "dealbreakers": "clearance; relocation"})
        assert r.status_code == 200
        assert r.json()["profile"]["home_country"] == "SA"
        assert r.json()["profile"]["dealbreakers"] == ["clearance", "relocation"]
        assert client.get("/profile").json()["exists"] is True

    @pytest.mark.parametrize("body", [{"home_country": "Atlantis"}, {"hobby": "x"}, {"salary_floor": "abc"}])
    def test_invalid_profiles_are_rejected_with_a_reason(self, client, body):
        r = client.put("/profile", json=body)
        assert r.status_code == 422 and r.json()["detail"]
        assert not prof.exists()

    def test_put_rechecks_saved_jobs(self, client):
        db.init()
        db.upsert_job("Dev", "c", "https://x.com/1", "s", "", 5, "", location="Austin", remote=False, description="x")
        r = client.put("/profile", json={"home_country": "AE"})
        assert r.json()["reevaluated"]["not_eligible"] == 1
        assert db.list_jobs()[0]["eligibility"] == "not_eligible"

    def test_profile_endpoints_need_the_token_when_one_is_set(self, client, monkeypatch):
        monkeypatch.setenv("API_TOKEN", "s3cret")
        assert client.get("/profile").status_code == 401
        assert client.put("/profile", json={}).status_code == 401
        assert client.get("/profile", headers={"Authorization": "Bearer s3cret"}).status_code == 200


class TestJobFiltersApi:

    def seed(self):
        db.init()
        for title, verdict, reasons in (("A", "eligible", ["ok"]), ("B", "not_eligible", ["far", "away"]), ("C", None, None)):
            db.upsert_job(title, "c", f"https://x.com/{title}", "s", "", 5, "", eligibility=verdict, eligibility_reasons=reasons)

    def test_jobs_filter(self, client):
        self.seed()
        titles = lambda q: sorted(j["title"] for j in client.get(f"/jobs?{q}").json()["jobs"])
        assert titles("eligibility=eligible") == ["A"]
        assert titles("eligibility=eligible,unchecked") == ["A", "C"]
        assert titles("") == ["A", "B", "C"]

    def test_csv_export_flattens_reasons(self, client):
        self.seed()
        text = client.get("/export/csv?eligibility=not_eligible").text
        assert "far; away" in text and "eligibility_reasons" in text

    def test_json_export_keeps_reasons_as_a_list(self, client):
        self.seed()
        rows = client.get("/export/json?eligibility=not_eligible").json()
        assert rows[0]["eligibility_reasons"] == ["far", "away"]


class TestProfileCli:

    def test_set_then_show(self, capsys):
        assert cli.main(["profile", "set", "--home-country", "AE", "--work-authorization", "GCC",
                         "--needs-visa", "--salary-floor", "60000", "--dealbreakers", "clearance"]) == 0
        capsys.readouterr()
        assert cli.main(["profile", "show", "--json"]) == 0
        saved = json.loads(capsys.readouterr().out)
        assert saved["home_country"] == "AE" and saved["needs_visa"] is True and saved["salary_floor"] == 60000

    def test_no_needs_visa_flag_turns_it_off(self, capsys):
        cli.main(["profile", "set", "--needs-visa"])
        cli.main(["profile", "set", "--no-needs-visa"])
        assert prof.load()["needs_visa"] is False

    def test_set_rechecks_saved_jobs_and_reports_counts(self, capsys):
        db.init()
        db.upsert_job("Dev", "c", "https://x.com/1", "s", "", 5, "", location="Dubai", remote=False)
        cli.main(["profile", "set", "--home-country", "AE"])
        assert "1 eligible" in capsys.readouterr().err

    def test_bad_values_fail_with_exit_2_and_a_message(self, capsys):
        assert cli.main(["profile", "set", "--home-country", "Atlantis"]) == 2
        assert "profile error" in capsys.readouterr().err
        assert not prof.exists()

    def test_set_without_options_is_an_error(self, capsys):
        assert cli.main(["profile", "set"]) == 2

    def test_cv_file_is_read(self, tmp_path):
        cv = tmp_path / "cv.txt"
        cv.write_text("python developer")
        cli.main(["profile", "set", "--cv-file", str(cv)])
        assert prof.load()["cv_text"] == "python developer"

    def test_missing_cv_file_is_reported(self, capsys):
        assert cli.main(["profile", "set", "--cv-file", "/no/such/file"]) == 2

    def test_export_can_filter_by_eligibility(self, capsys):
        db.init()
        db.upsert_job("A", "c", "https://x.com/a", "s", "", 5, "", eligibility="eligible")
        db.upsert_job("B", "c", "https://x.com/b", "s", "", 5, "", eligibility="not_eligible")
        cli.main(["export", "--eligibility", "eligible"])
        rows = json.loads(capsys.readouterr().out)
        assert [r["title"] for r in rows] == ["A"]


class TestPromptIncludesProfile:

    def test_profile_lines_reach_the_ai_prompt(self):
        from jobsieve.ai_service import AIService

        p = prof.normalize({"home_country": "AE", "work_authorization": ["GCC"], "needs_visa": True,
                            "salary_floor": 60000, "dealbreakers": ["clearance"]})
        prompt = AIService("groq", {}).build_prompt("job text", "my cv", ["python"], p)
        assert "lives in United Arab Emirates" in prompt and "Needs visa sponsorship" in prompt
        assert "60,000 USD" in prompt and "clearance" in prompt

    def test_prompt_without_profile_is_unchanged(self):
        from jobsieve.ai_service import AIService

        prompt = AIService("groq", {}).build_prompt("job text", "my cv", ["python"])
        assert "Candidate lives" not in prompt and "my cv" in prompt
