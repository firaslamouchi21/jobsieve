import json

import pytest

from jobsieve import cli, db
from jobsieve.sources import REGISTRY, SourceError


def fetch_json(capsys, *args):
    code = cli.main(["fetch", *args, "--json"])
    return code, capsys.readouterr()


class TestFetchCommand:

    def test_json_output_is_pure_json_with_normalized_fields(self, capsys):
        code, out = fetch_json(capsys, "--source", "remoteok", "--keyword", "python")
        assert code == 0
        rows = json.loads(out.out)
        assert len(rows) == 2
        row = rows[0]
        for field in ("title", "company", "location", "remote", "salary", "posted_at",
                      "url", "description", "source", "job_hash", "is_new", "attribution"):
            assert field in row
        assert row["source"] == "remoteok"
        assert row["attribution"] == "Remote OK"

    def test_records_are_stored_unscored_and_marked_new_once(self, capsys):
        _, first = fetch_json(capsys, "--source", "remoteok", "--keyword", "python")
        _, second = fetch_json(capsys, "--source", "remoteok", "--keyword", "python")
        assert all(r["is_new"] for r in json.loads(first.out))
        assert not any(r["is_new"] for r in json.loads(second.out))
        assert db.count_jobs() == 2
        assert all(j["score"] is None for j in db.list_jobs())

    def test_job_hash_matches_database_so_an_agent_can_score(self, capsys):
        _, out = fetch_json(capsys, "--source", "remotive", "--keyword", "python")
        row = json.loads(out.out)[0]
        assert db.set_score(row["job_hash"], 8, "good fit") is True
        stored = next(j for j in db.list_jobs() if j["job_hash"] == row["job_hash"])
        assert (stored["score"], stored["reasoning"]) == (8, "good fit")

    def test_no_store_leaves_database_empty(self, capsys):
        _, out = fetch_json(capsys, "--source", "arbeitnow", "--keyword", "python", "--no-store")
        rows = json.loads(out.out)
        assert rows and rows[0]["is_new"] is None
        db.init()
        assert db.count_jobs() == 0

    def test_multiple_sources_and_limit(self, capsys):
        _, out = fetch_json(capsys, "--source", "remoteok", "remotive", "--keyword", "python", "--limit", "1")
        assert [r["source"] for r in json.loads(out.out)] == ["remoteok", "remotive"]

    def test_keyword_filters_results(self, capsys):
        _, out = fetch_json(capsys, "--source", "remoteok", "--keyword", "cobol")
        assert json.loads(out.out) == []

    def test_ddg_source_works_with_sites(self, capsys):
        _, out = fetch_json(capsys, "--source", "ddg", "--keyword", "python", "--site", "example.com")
        rows = json.loads(out.out)
        assert rows[0]["source"] == "ddg" and rows[0]["company"] == "example.com"

    def test_plain_output_lists_listings(self, capsys):
        code = cli.main(["fetch", "--source", "remoteok", "--keyword", "python"])
        out = capsys.readouterr()
        assert code == 0
        assert "Mock Python Developer" in out.out and "via Remote OK" in out.out
        assert "2 listings" in out.err


class TestFetchErrors:

    def test_unknown_source_exits_2_and_lists_choices(self, capsys):
        code = cli.main(["fetch", "--source", "linkedin", "--json"])
        assert code == 2
        assert "available: ddg" in capsys.readouterr().err

    def test_one_failing_source_does_not_hide_the_others(self, capsys, monkeypatch):
        def boom(keywords, limit=50, **options):
            raise SourceError("remotive: offline")

        monkeypatch.setattr(REGISTRY["remotive"], "fetch", boom)
        code, out = fetch_json(capsys, "--source", "remotive", "remoteok", "--keyword", "python")
        assert code == 0
        assert {r["source"] for r in json.loads(out.out)} == {"remoteok"}
        assert "remotive: offline" in out.err

    def test_all_sources_failing_exits_3_with_valid_empty_json(self, capsys, monkeypatch):
        def boom(keywords, limit=50, **options):
            raise SourceError("offline")

        monkeypatch.setattr(REGISTRY["remoteok"], "fetch", boom)
        code, out = fetch_json(capsys, "--source", "remoteok", "--keyword", "python")
        assert code == 3
        assert json.loads(out.out) == []


class TestOtherCommands:

    def test_sources_command_lists_attribution(self, capsys):
        assert cli.main(["sources"]) == 0
        out = capsys.readouterr().out
        assert "remoteok\tRemote OK\thttps://remoteok.com" in out

    def test_run_accepts_sources_flag(self):
        code = cli.main(["run", "--lite", "--sources", "remoteok", "remotive", "--keywords", "python"])
        assert code == 0
        assert db.count_jobs() == 4
