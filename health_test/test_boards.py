import pytest

from jobsieve import cli, watchlist
from jobsieve.sources import boards, base, get_source

GREENHOUSE = {"jobs": [{"title": "Account Manager I", "company_name": "Careem", "absolute_url": "https://boards.greenhouse.io/careem/jobs/1",
                        "location": {"name": "Dubai, United Arab Emirates"}, "first_published": "2026-10-09T02:50:57-04:00",
                        "content": "&lt;p&gt;Manage &amp;amp; grow accounts&lt;/p&gt;"}]}
LEVER = [{"text": "Backend Engineer", "hostedUrl": "https://jobs.lever.co/acme/1", "categories": {"location": "Singapore"},
          "workplaceType": "remote", "createdAt": 1786469891368, "descriptionPlain": "Build python services"}]
ASHBY = {"jobs": [{"title": "EM - EU", "jobUrl": "https://jobs.ashbyhq.com/a/1", "location": "Remote - European Union",
                   "isRemote": True, "publishedAt": "2024-03-04T14:29:08+00:00", "descriptionPlain": "Lead a team"},
                  {"title": "Hidden", "isListed": False, "jobUrl": "u"}]}
SMART = {"content": [{"id": "7", "name": "Ops Manager", "company": {"name": "Acme Inc"},
                      "releasedDate": "2026-10-28T15:14:43.941Z", "department": {"label": "Operations"},
                      "location": {"fullLocation": "Poland, Remote", "remote": True}}]}


def test_greenhouse():
    record = boards.parse_greenhouse(GREENHOUSE, "careem")[0]
    assert (record.company, record.location, record.source) == ("Careem", "Dubai, United Arab Emirates", "greenhouse")
    assert record.description == "Manage & grow accounts"


def test_lever_maps_workplace_and_time():
    record = boards.parse_lever(LEVER, "acme")[0]
    assert record.remote is True and record.location == "Singapore" and record.posted_at.startswith("2026-")


def test_ashby_skips_unlisted():
    records = boards.parse_ashby(ASHBY, "a")
    assert [r.title for r in records] == ["EM - EU"] and records[0].remote is True


def test_smartrecruiters_builds_public_url():
    record = boards.parse_smartrecruiters(SMART, "acme")[0]
    assert record.url == "https://jobs.smartrecruiters.com/acme/7"
    assert record.company == "Acme Inc" and record.remote is True


@pytest.mark.parametrize("parser", [boards.parse_greenhouse, boards.parse_lever, boards.parse_ashby, boards.parse_smartrecruiters])
def test_parsers_tolerate_garbage(parser):
    for junk in (None, {"x": 1}, [1, "a", None], "text"):
        assert parser(junk, "s") == []


class TestWatchlist:

    def test_add_list_remove_and_duplicates(self):
        assert watchlist.add("greenhouse", "careem") is True
        assert watchlist.add("Greenhouse", "Careem") is False
        assert watchlist.load() == [{"board": "greenhouse", "slug": "careem", "added_by": "manual"}]
        assert watchlist.remove("greenhouse", "CAREEM") is True
        assert watchlist.remove("greenhouse", "careem") is False

    @pytest.mark.parametrize("board,slug", [("workday", "x"), ("lever", "../etc"), ("lever", ""), ("lever", "a b")])
    def test_rejects_bad_input(self, board, slug):
        with pytest.raises(watchlist.WatchlistError):
            watchlist.add(board, slug)

    def test_unreadable_file_is_reported(self):
        import os
        os.makedirs(os.environ["DATA_DIR"], exist_ok=True)
        with open(watchlist.watchlist_path(), "w") as f:
            f.write("{not json")
        with pytest.raises(watchlist.WatchlistError):
            watchlist.load()


class TestBoardsSource:

    @pytest.fixture(autouse=True)
    def live_mode(self, monkeypatch):
        monkeypatch.setenv("MOCK_SEARCH", "false")

    def test_reads_each_watched_company_and_filters(self, monkeypatch):
        watchlist.add("greenhouse", "careem")
        watchlist.add("lever", "acme")
        monkeypatch.setattr(boards, "sleep_delay", lambda: None)
        payloads = {"careem": GREENHOUSE, "acme": LEVER}
        monkeypatch.setattr(base, "fetch_json", lambda url: payloads["careem" if "careem" in url else "acme"])
        found = get_source("boards").fetch(["python"])
        assert [r.title for r in found] == ["Backend Engineer"]
        assert len(get_source("boards").fetch([])) == 2

    def test_one_broken_company_does_not_stop_the_rest(self, monkeypatch):
        watchlist.add("greenhouse", "gone")
        watchlist.add("lever", "acme")
        monkeypatch.setattr(boards, "sleep_delay", lambda: None)

        def fake(url):
            if "gone" in url:
                raise RuntimeError("404")
            return LEVER

        monkeypatch.setattr(base, "fetch_json", fake)
        assert len(get_source("boards").fetch([])) == 1

    def test_empty_watchlist_returns_nothing(self):
        assert get_source("boards").fetch(["python"]) == []

    def test_mock_mode_is_offline(self, monkeypatch):
        monkeypatch.setenv("MOCK_SEARCH", "true")
        monkeypatch.setattr(base, "fetch_json", lambda url: (_ for _ in ()).throw(AssertionError("network")))
        assert len(get_source("boards").fetch(["python"])) == 2


class TestWatchCli:

    def test_add_list_remove(self, capsys):
        assert cli.run_watch(cli.parse_args(["watch", "add", "ashby", "ashby"])) == 0
        cli.run_watch(cli.parse_args(["watch", "list"]))
        assert "ashby" in capsys.readouterr().out
        assert cli.run_watch(cli.parse_args(["watch", "remove", "ashby", "ashby"])) == 0

    def test_bad_name_exits_2(self):
        assert cli.run_watch(cli.parse_args(["watch", "add", "lever", "a b"])) == 2

    def test_check_reports_failures(self, monkeypatch, capsys):
        watchlist.add("lever", "acme")
        monkeypatch.setattr(boards, "fetch_board", lambda b, s: (_ for _ in ()).throw(RuntimeError("404")))
        monkeypatch.setattr("jobsieve.util.sleep_delay", lambda: None)
        assert cli.run_watch(cli.parse_args(["watch", "check"])) == 1
        assert "FAILED" in capsys.readouterr().out


class TestWatchlistApi:

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from jobsieve.api import api
        return TestClient(api)

    def test_add_list_remove(self, client):
        assert client.post("/watchlist", json={"board": "lever", "company": "acme"}).json() == {"added": True, "jobs_found": None}
        assert client.post("/watchlist", json={"board": "lever", "company": "acme"}).json()["added"] is False
        assert client.get("/watchlist").json()["companies"][0]["slug"] == "acme"
        assert client.delete("/watchlist/lever/acme").status_code == 200
        assert client.delete("/watchlist/lever/acme").status_code == 404

    def test_bad_input_is_rejected(self, client):
        assert client.post("/watchlist", json={"board": "workday", "company": "x"}).status_code == 422
        assert client.post("/watchlist", json={"board": "lever", "company": "a b"}).status_code == 422

    def test_verify_counts_jobs_or_refuses_unknown_companies(self, client, monkeypatch):
        monkeypatch.setattr(boards, "fetch_board", lambda b, s: [1, 2, 3])
        r = client.post("/watchlist", json={"board": "lever", "company": "acme", "verify": True})
        assert r.json() == {"added": True, "jobs_found": 3}
        monkeypatch.setattr(boards, "fetch_board", lambda b, s: (_ for _ in ()).throw(RuntimeError("404")))
        r = client.post("/watchlist", json={"board": "lever", "company": "ghost", "verify": True})
        assert r.status_code == 422 and "ghost" in r.json()["detail"]
        assert [c["slug"] for c in client.get("/watchlist").json()["companies"]] == ["acme"]

    def test_needs_the_token_when_one_is_set(self, client, monkeypatch):
        monkeypatch.setenv("API_TOKEN", "secret")
        assert client.get("/watchlist").status_code == 401
        assert client.get("/watchlist", headers={"Authorization": "Bearer secret"}).status_code == 200


class TestStarterLists:

    def test_every_entry_is_valid(self):
        lists = watchlist.starter_lists()
        assert "gulf-mena" in lists
        for data in lists.values():
            assert data["description"]
            for company in data["companies"]:
                assert company["board"] in watchlist.BOARDS and watchlist.SLUG.match(company["slug"])

    def test_adding_twice_adds_nothing_new_and_marks_the_origin(self):
        first = watchlist.add_starter("gulf-mena")
        assert first == len(watchlist.starter_lists()["gulf-mena"]["companies"])
        assert watchlist.add_starter("gulf-mena") == 0
        assert watchlist.load()[0]["added_by"] == "starter:gulf-mena"

    def test_unknown_list_and_cli(self, capsys):
        with pytest.raises(watchlist.WatchlistError):
            watchlist.add_starter("nope")
        assert cli.run_watch(cli.parse_args(["watch", "starter"])) == 0
        assert "gulf-mena" in capsys.readouterr().out
        assert cli.run_watch(cli.parse_args(["watch", "starter", "nope"])) == 2
        assert cli.run_watch(cli.parse_args(["watch", "starter", "gulf-mena"])) == 0
