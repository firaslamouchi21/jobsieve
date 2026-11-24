import io
import json

import pytest

from jobsieve import cli, crawler, watchlist
from jobsieve.careers import CareerPageError
from jobsieve.sources import get_source

POSTING = {"@type": "JobPosting", "title": "Data Engineer", "hiringOrganization": {"name": "Acme"},
           "jobLocation": {"address": {"addressLocality": "Dubai", "addressCountry": "AE"}},
           "datePosted": "2026-11-20", "description": "<p>Build pipelines</p>", "url": "https://acme.com/jobs/data-engineer"}


def page(*blocks, body=""):
    scripts = "".join(f'<script type="application/ld+json">{json.dumps(b)}</script>' for b in blocks)
    return f"<html><head>{scripts}</head><body>{body}</body></html>"


class Raw:
    def __init__(self, data): self.stream = io.BytesIO(data)
    def read(self, n, decode_content=True): return self.stream.read(n)


class Response:
    def __init__(self, text="", status=200, headers=None):
        self.status_code, self.headers, self.encoding = status, headers or {}, "utf-8"
        self.raw = Raw(text.encode())
        self.text = text
    @property
    def is_redirect(self): return 300 <= self.status_code < 400
    def close(self): pass


class Web:
    def __init__(self, pages, robots="User-agent: *\nAllow: /"):
        self.pages, self.robots, self.calls = pages, robots, []

    def __call__(self, url, **kwargs):
        self.calls.append(url)
        if url.endswith("/robots.txt"):
            return self.robots if isinstance(self.robots, Response) else Response(self.robots)
        value = self.pages.get(url)
        if isinstance(value, Response):
            return value
        return Response(value, 200) if value is not None else Response("", 404)


@pytest.fixture
def web(monkeypatch):
    monkeypatch.setattr(crawler, "check_public_url", lambda u: u)
    def install(pages, **kw):
        fake = Web(pages, **kw)
        monkeypatch.setattr(crawler.requests, "get", fake)
        return fake
    return install


def fetcher():
    f = crawler.PoliteFetcher(sleep=lambda s: None)
    return f


class TestParsing:

    def test_reads_single_list_graph_and_itemlist(self):
        assert len(crawler.job_postings(POSTING)) == 1
        assert len(crawler.job_postings([POSTING, {"@type": "Organization"}])) == 1
        assert len(crawler.job_postings({"@graph": [POSTING, POSTING]})) == 2
        assert len(crawler.job_postings({"@type": "ItemList", "itemListElement": [{"item": POSTING}, {"item": POSTING}]})) == 2
        assert crawler.job_postings({"@type": ["Thing", "JobPosting"]}) != []
        assert crawler.job_postings("junk") == []

    def test_record_fields(self):
        record = crawler.record_from_posting(POSTING, "https://acme.com/careers", "web")
        assert (record.title, record.company, record.location) == ("Data Engineer", "Acme", "Dubai, AE")
        assert record.description == "Build pipelines" and record.url == "https://acme.com/jobs/data-engineer"

    def test_posting_without_title_is_skipped(self):
        assert crawler.record_from_posting({"@type": "JobPosting"}, "u", "web") is None

    def test_bad_json_ld_is_ignored(self):
        assert crawler.json_ld_blocks('<script type="application/ld+json">{oops</script>') == []

    def test_detail_links_stay_on_the_site_and_look_like_jobs(self):
        html = ('<a href="/jobs/one">1</a><a href="https://acme.com/careers/two">2</a><a href="https://other.com/jobs/x">x</a>'
                '<a href="/about">about</a><a href="/jobs/one#top">dup</a>')
        assert crawler.detail_links(html, "https://acme.com/careers") == ["https://acme.com/jobs/one", "https://acme.com/careers/two"]


class TestFetcher:

    def test_listing_page_with_postings_is_read_directly(self, web):
        fake = web({"https://acme.com/careers": page(POSTING)})
        assert [r.title for r in crawler.read_jobs(fetcher(), "https://acme.com/careers")] == ["Data Engineer"]
        assert fake.calls == ["https://acme.com/robots.txt", "https://acme.com/careers"]

    def test_follows_job_links_when_the_listing_has_no_data(self, web):
        web({"https://acme.com/careers": page(body='<a href="/jobs/de">de</a><a href="/jobs/gone">gone</a>'),
             "https://acme.com/jobs/de": page(POSTING)})
        assert len(crawler.read_jobs(fetcher(), "https://acme.com/careers")) == 1

    def test_robots_disallow_is_respected(self, web):
        fake = web({"https://acme.com/careers": page(POSTING)}, robots="User-agent: *\nDisallow: /careers")
        with pytest.raises(CareerPageError, match="robots"):
            crawler.read_jobs(fetcher(), "https://acme.com/careers")
        assert "https://acme.com/careers" not in fake.calls

    def test_a_forbidden_robots_file_means_no(self, web):
        fake = web({"https://acme.com/careers": page(POSTING)})
        fake.robots = Response("", 403)
        assert fetcher().allowed("https://acme.com/careers") is False

    def test_a_missing_robots_file_means_yes(self, web):
        fake = web({})
        fake.robots = Response("", 404)
        assert fetcher().allowed("https://acme.com/careers") is True

    @pytest.mark.parametrize("response", [
        Response("blocked", 403), Response("", 429), Response("<html>Please complete the CAPTCHA</html>", 200),
        Response("<html>cf-chl-bypass</html>", 200),
    ])
    def test_a_bot_check_stops_that_site(self, web, response):
        fake = web({"https://acme.com/careers": response, "https://acme.com/other": page(POSTING)})
        f = fetcher()
        with pytest.raises(crawler.BotChallenge):
            f.get("https://acme.com/careers")
        calls = len(fake.calls)
        with pytest.raises(crawler.BotChallenge, match="stopped"):
            f.get("https://acme.com/other")
        assert len(fake.calls) == calls

    def test_a_long_normal_page_mentioning_captcha_is_fine(self):
        assert crawler.PoliteFetcher.looks_like_challenge("captcha " + "x" * 30000) is False

    def test_waits_between_requests_to_the_same_site(self, web):
        web({"https://acme.com/a": "a", "https://acme.com/b": "b"})
        sleeps, now = [], [0.0]
        f = crawler.PoliteFetcher(sleep=sleeps.append, clock=lambda: now[0])
        f.get("https://acme.com/a")
        now[0] = 0.5
        f.get("https://acme.com/b")
        assert sleeps and sleeps[0] == pytest.approx(f.delay - 0.5) and f.delay >= 2.0

    def test_redirect_to_another_site_is_refused(self, web):
        web({"https://acme.com/a": Response("", 301, {"Location": "https://evil.com/x"})})
        with pytest.raises(CareerPageError, match="another site"):
            fetcher().get("https://acme.com/a")

    def test_private_addresses_are_refused(self):
        with pytest.raises(CareerPageError):
            fetcher().get("http://127.0.0.1/admin")


class TestWebSource:

    @pytest.fixture(autouse=True)
    def live(self, monkeypatch):
        monkeypatch.setenv("MOCK_SEARCH", "false")
        monkeypatch.setattr(crawler.time, "sleep", lambda s: None)
        monkeypatch.setattr(crawler, "MIN_DELAY_SECONDS", 0.0)
        monkeypatch.setattr(crawler, "REQUEST_DELAY_SECONDS", 0.0)

    def test_reads_listed_pages_filters_and_caches(self, web):
        fake = web({"https://acme.com/careers": page(POSTING), "https://bad.com/x": Response("", 500)})
        watchlist.add_page("https://acme.com/careers")
        watchlist.add_page("https://bad.com/x")
        found = get_source("web").fetch(["pipelines"])
        assert [r.title for r in found] == ["Data Engineer"]
        calls = len(fake.calls)
        assert get_source("web").fetch(["python"]) == []
        assert not [c for c in fake.calls[calls:] if c == "https://acme.com/careers"]

    def test_no_pages_no_requests(self, web):
        fake = web({})
        assert get_source("web").fetch(["x"]) == [] and fake.calls == []


def test_page_list_commands(capsys):
    assert cli.run_watch(cli.parse_args(["watch", "add-page", "https://acme.com/careers"])) == 0
    assert cli.run_watch(cli.parse_args(["watch", "add-page", "ftp://x"])) == 2
    cli.run_watch(cli.parse_args(["watch", "list"]))
    assert "https://acme.com/careers" in capsys.readouterr().out
    assert cli.run_watch(cli.parse_args(["watch", "remove-page", "https://acme.com/careers"])) == 0
    assert watchlist.load_pages() == []


@pytest.mark.parametrize("url,refused", [
    ("https://www.linkedin.com/jobs/view/1", True), ("https://uk.indeed.com/jobs", True), ("https://ae.indeed.com/x", True),
    ("https://www.glassdoor.com/Job/x", True), ("https://www.glassdoor.co.uk/Job/x", True),
    ("https://notlinkedin.com/x", False), ("https://acme.com/indeed.com", False), ("https://www.bayt.com/en/uae/jobs/", False),
])
def test_sites_whose_terms_forbid_it_are_refused(url, refused):
    assert bool(crawler.refused_site(url)) is refused


def test_refused_sites_cannot_be_added_or_fetched():
    with pytest.raises(watchlist.WatchlistError, match="extension"):
        watchlist.add_page("https://www.linkedin.com/jobs/view/1")
    with pytest.raises(CareerPageError, match="extension"):
        fetcher().get("https://uk.indeed.com/jobs")
