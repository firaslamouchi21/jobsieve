import pytest
import requests

from jobsieve import careers, cli, watchlist

REAL_READ_PAGE = careers.read_page
HTML = """
<html><script src="https://boards.greenhouse.io/embed/job_board/js?for=acme"></script>
<a href="https://jobs.lever.co/other/123">Apply</a>
<script>var u = "https:\\/\\/jobs.ashbyhq.com\\/zeta";</script>
<a href="https://example.com/jobs">x</a><a href="https://jobs.lever.co/other/456">dup</a></html>
"""


def test_boards_are_found_in_links_embeds_and_escaped_urls():
    assert careers.boards_in_html(HTML) == [("greenhouse", "acme"), ("lever", "other"), ("ashby", "zeta")]
    assert careers.boards_in_html("") == []


@pytest.mark.parametrize("url", [
    "ftp://example.com", "file:///etc/passwd", "http://127.0.0.1/admin", "http://localhost:8000/",
    "http://169.254.169.254/latest/meta-data", "http://10.0.0.5/", "http://[::1]/", "not a url",
])
def test_private_and_odd_addresses_are_refused(url):
    with pytest.raises(careers.CareerPageError):
        careers.check_public_url(url)


def test_a_redirect_to_a_private_address_is_refused(monkeypatch):
    monkeypatch.setattr(careers, "robots_allow", lambda u: True)
    checked = []

    def strict(url):
        checked.append(url)
        if "127.0.0.1" in url:
            raise careers.CareerPageError("only public web addresses can be read")
        return url

    class Redirect:
        is_redirect = True
        headers = {"Location": "http://127.0.0.1/secret"}
        def close(self): pass

    monkeypatch.setattr(careers, "check_public_url", strict)
    monkeypatch.setattr(careers.requests, "get", lambda *a, **k: Redirect())
    with pytest.raises(careers.CareerPageError, match="public"):
        careers.read_page("https://example.com/careers")
    assert checked == ["https://example.com/careers", "http://127.0.0.1/secret"]


def test_robots_txt_is_respected(monkeypatch):
    class Response:
        status_code = 200
        text = "User-agent: *\nDisallow: /careers"

    monkeypatch.setattr(careers.requests, "get", lambda *a, **k: Response())
    assert careers.robots_allow("https://example.com/careers") is False
    assert careers.robots_allow("https://example.com/about") is True


def test_missing_robots_txt_allows_reading(monkeypatch):
    class Gone:
        status_code = 404
        text = ""

    monkeypatch.setattr(careers.requests, "get", lambda *a, **k: Gone())
    assert careers.robots_allow("https://example.com/careers") is True
    monkeypatch.setattr(careers.requests, "get", lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError()))
    assert careers.robots_allow("https://example.com/careers") is True


def test_a_board_address_needs_no_fetch(monkeypatch):
    monkeypatch.setattr(careers, "read_page", lambda u: (_ for _ in ()).throw(AssertionError("fetched")))
    assert careers.find_boards("https://jobs.lever.co/palantir") == [("lever", "palantir")]


def test_add_from_page_marks_the_source(monkeypatch):
    monkeypatch.setattr(careers, "read_page", lambda u: HTML)
    assert [a for _, _, a in careers.add_from_page("https://example.com/careers")] == [True, True, True]
    assert [a for _, _, a in careers.add_from_page("https://example.com/careers")] == [False, False, False]
    assert watchlist.load()[0]["added_by"] == "career page"


def test_cli_and_api(monkeypatch, capsys):
    from fastapi.testclient import TestClient
    from jobsieve.api import api

    monkeypatch.setattr(careers, "read_page", lambda u: HTML)
    assert cli.run_watch(cli.parse_args(["watch", "from-page", "https://example.com/careers"])) == 0
    assert "added: greenhouse acme" in capsys.readouterr().out
    client = TestClient(api)
    r = client.post("/watchlist/from-page", json={"url": "https://example.com/careers"})
    assert r.status_code == 200 and not any(c["added"] for c in r.json()["companies"])
    monkeypatch.setattr(careers, "read_page", lambda u: "<html>nothing</html>")
    assert client.post("/watchlist/from-page", json={"url": "https://example.com/x"}).json() == {"companies": []}
    monkeypatch.setattr(careers, "read_page", REAL_READ_PAGE)
    assert client.post("/watchlist/from-page", json={"url": "http://127.0.0.1/"}).status_code == 422
    assert cli.run_watch(cli.parse_args(["watch", "from-page", "http://127.0.0.1/"])) == 2
