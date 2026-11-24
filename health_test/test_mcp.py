import asyncio
import json
import os
import subprocess
import sys

import pytest

from jobsieve import db, mcp_server as m
from jobsieve import profile as prof
from jobsieve.sources.base import JobRecord


def seed(url="https://x/1", **kw):
    db.init()
    record = JobRecord(title="Data Engineer", company="Acme", url=url, source="lever", location="Dubai",
                       description="Python pipelines. " * 800, **kw)
    db.upsert_record(record, 5, "matched_keywords=1", description=record.description)
    return db.record_hash(record)


class TestTools:

    def test_search_stores_matches_and_checks_eligibility(self):
        prof.save({"home_country": "AE", "work_authorization": ["GCC"], "keywords": ["python"]})
        out = m.search_jobs(["python"], ["remoteok", "nonsense"], limit=5)
        assert len(out["jobs"]) == 2 and "nonsense" in out["errors"]
        assert out["jobs"][0]["eligibility"] in ("eligible", "unknown", "not_eligible")
        assert len(db.list_jobs(include_closed=True)) == 2

    def test_list_is_brief_and_get_has_the_description(self):
        h = seed()
        brief = m.list_jobs()["jobs"][0]
        assert len(brief["snippet"]) <= 400 and "description" not in brief
        full = m.get_job(h[:10])
        assert full["description"].startswith("Python") and len(full["description"]) <= 12000

    def test_agent_scores_survive_a_refresh(self):
        h = seed()
        m.set_score(h[:8], 15, "fits well")
        job = db.get_job(h)
        assert job["score"] == 10 and job["reasoning"] == "agent: fits well"
        seed()
        assert db.get_job(h)["score"] == 10

    def test_status_notes_and_hidden(self):
        h = seed()
        assert m.set_status(h[:8], "applied", "sent")["status"] == "applied"
        assert m.list_jobs()["jobs"][0]["status"] == "applied"
        m.set_status(h[:8], "hidden")
        assert m.list_jobs()["jobs"] == [] and len(m.list_jobs(status=["hidden"])["jobs"]) == 1
        with pytest.raises(ValueError):
            m.set_status(h[:8], "maybe")

    @pytest.mark.parametrize("bad", ["", "abc", "zzzzzzzz"])
    def test_unknown_or_short_ids_are_refused(self, bad):
        seed()
        with pytest.raises(ValueError, match="no job matches"):
            m.get_job(bad)

    def test_application_draft_is_saved_and_checked_for_made_up_numbers(self):
        prof.save({"cv_text": "Python engineer, 3 years."})
        h = seed()
        out = m.save_application_draft(h, ["Lead with Python"], ["Kubernetes"], "I ran 40 pipelines over 3 years.")
        assert out["unverified_numbers"] == ["40"]
        assert db.get_job(h)["tailoring"]["provider"] == "agent"

    def test_profile_watchlist_digest_sources(self):
        assert m.get_profile()["exists"] is False
        assert m.watch_company("lever", "acme") == {"added": True}
        assert m.digest() == {"count": 0, "markdown": ""}
        assert "boards" in m.list_sources()["sources"]


mcp = pytest.importorskip("mcp")


class TestServer:

    def test_every_tool_is_registered_with_a_description(self):
        tools = asyncio.run(m.build_server().list_tools())
        assert {t.name for t in tools} == {f.__name__ for f in m.TOOLS}
        assert all(t.description for t in tools)

    def test_speaks_mcp_over_stdio(self, tmp_path):
        env = {**os.environ, "DATA_DIR": str(tmp_path), "MOCK_SEARCH": "true"}
        proc = subprocess.Popen([sys.executable, "-c", "from jobsieve import mcp_server; mcp_server.main()"],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)

        def send(message):
            proc.stdin.write(json.dumps(message) + "\n"); proc.stdin.flush()

        def receive():
            while True:
                line = proc.stdout.readline()
                if not line:
                    return None
                try:
                    return json.loads(line)
                except ValueError:
                    continue

        try:
            send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}})
            assert receive()["result"]["serverInfo"]["name"] == "jobsieve"
            send({"jsonrpc": "2.0", "method": "notifications/initialized"})
            send({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "list_sources", "arguments": {}}})
            assert "remoteok" in json.dumps(receive()["result"])
        finally:
            proc.kill()
