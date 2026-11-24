import json
import os
import time

import pytest

from jobsieve.sources import (
    REGISTRY,
    JobRecord,
    SourceError,
    arbeitnow,
    available_sources,
    base,
    ddg,
    get_source,
    himalayas,
    jobicy,
    remoteok,
    remotive,
    workingnomads,
)
from jobsieve.util import normalize_url

REMOTEOK_PAYLOAD = [
    {"last_updated": 1, "legal": "API Terms of Service: link back"},
    {
        "slug": "python-dev",
        "id": "1",
        "date": "2026-11-11T08:00:08+00:00",
        "company": "Acme",
        "position": "Senior Python Developer",
        "tags": ["python"],
        "description": "<p>Build <b>APIs</b> in Python.</p>",
        "location": "Worldwide",
        "salary_min": 80000,
        "salary_max": 120000,
        "url": "https://remoteOK.com/remote-jobs/python-dev-1",
    },
    {
        "position": "Designer",
        "company": "Pixel",
        "date": "2026-11-10T08:00:08+00:00",
        "description": "<p>Draw things</p>",
        "salary_min": 0,
        "salary_max": 0,
        "url": "https://remoteOK.com/remote-jobs/designer-2",
    },
]
REMOTIVE_PAYLOAD = {
    "00-warning": "x",
    "jobs": [
        {
            "id": 7,
            "url": "https://remotive.com/remote-jobs/software-dev/backend-7",
            "title": "Backend Engineer",
            "company_name": "Coalition ",
            "candidate_required_location": "Worldwide",
            "salary": "$50k-$70k",
            "publication_date": "2026-11-11T20:17:48",
            "description": '<p class="h3">Python and Go</p>',
        }
    ],
}
ARBEITNOW_PAYLOAD = {
    "data": [
        {
            "slug": "dev-berlin",
            "company_name": "Berlin GmbH",
            "title": "Python Entwickler (m/w/d)",
            "description": "<p>Python, Django</p>",
            "remote": False,
            "url": "https://www.arbeitnow.com/jobs/companies/berlin/dev-berlin",
            "location": "Berlin",
            "created_at": 1794668451,
        }
    ],
    "links": {"next": None},
}


@pytest.fixture(autouse=True)
def real_mode(monkeypatch):
    monkeypatch.delenv("MOCK_SEARCH", raising=False)


class TestParsers:

    def test_remoteok_skips_legal_notice_and_normalizes(self):
        records = remoteok.parse(REMOTEOK_PAYLOAD)
        assert [r.title for r in records] == ["Senior Python Developer", "Designer"]
        first = records[0]
        assert first.company == "Acme"
        assert first.remote is True
        assert first.salary == "80000-120000"
        assert first.description == "Build APIs in Python."
        assert first.source == "remoteok"
        assert records[1].salary == ""

    def test_remotive_normalizes(self):
        record = remotive.parse(REMOTIVE_PAYLOAD)[0]
        assert record.company == "Coalition"
        assert record.salary == "$50k-$70k"
        assert record.location == "Worldwide"
        assert record.description == "Python and Go"
        assert record.source == "remotive"

    def test_himalayas_keeps_stated_location_restrictions(self):
        payload = {"jobs": [
            {"title": "Accountant", "companyName": "Acme", "guid": "https://himalayas.app/j/1",
             "locationRestrictions": ["United States", "Canada"], "minSalary": 90000, "maxSalary": 110000,
             "currency": "USD", "salaryPeriod": "annual", "pubDate": 1795436885, "description": "<p>Books</p>"},
            {"title": "Open role", "companyName": "Acme", "guid": "https://himalayas.app/j/2", "locationRestrictions": []},
        ]}
        first, second = himalayas.parse(payload)
        assert first.restrictions == "United States, Canada"
        assert first.salary == "USD 90000-110000/year"
        assert first.posted_at.startswith("2026-")
        assert first.description == "Books"
        assert second.restrictions == "" and second.remote is True

    def test_jobicy_normalizes_geo_and_salary(self):
        payload = {"jobs": [{"jobTitle": "Sales &amp; Ops", "companyName": "Cribl", "url": "https://jobicy.com/jobs/1",
                             "jobGeo": "Germany,  Netherlands,  UK", "salaryMin": 100000, "salaryMax": 130000,
                             "salaryCurrency": "EUR", "salaryPeriod": "yearly", "pubDate": "2026-11-23T09:13:41+00:00",
                             "jobDescription": "<p>Sell</p>"}]}
        record = jobicy.parse(payload)[0]
        assert record.title == "Sales & Ops"
        assert record.restrictions == "Germany, Netherlands, UK"
        assert record.salary == "EUR 100000-130000/year"

    def test_workingnomads_normalizes(self):
        payload = [{"url": "https://www.workingnomads.com/job/go/1/", "title": "Teacher", "company_name": "Polly",
                    "location": "North America", "pub_date": "2026-11-23T04:14:27-05:00", "description": "<p>Teach</p>"}]
        record = workingnomads.parse(payload)[0]
        assert record.restrictions == "North America"
        assert record.source == "workingnomads" and record.description == "Teach"

    def test_himalayas_follows_cursor_and_stops(self, monkeypatch):
        monkeypatch.setenv("HIMALAYAS_PAGES", "3")
        monkeypatch.setattr(himalayas, "sleep_delay", lambda: None)
        calls = []

        def fake(url):
            calls.append(url)
            return {"jobs": [{"title": f"J{len(calls)}", "guid": f"https://h/{len(calls)}"}], "nextCursor": f"c{len(calls)}"}

        monkeypatch.setattr(base, "fetch_json", fake)
        records = himalayas.HimalayasSource().download()
        assert len(records) == 3 and "cursor=c2" in calls[2] and "cursor" not in calls[0]

    def test_arbeitnow_normalizes_epoch_and_remote_flag(self):
        record = arbeitnow.parse(ARBEITNOW_PAYLOAD)[0]
        assert record.remote is False
        assert record.location == "Berlin"
        assert record.posted_at.startswith("2026-")
        assert record.source == "arbeitnow"

    @pytest.mark.parametrize("parser", [remoteok.parse, remotive.parse, arbeitnow.parse, himalayas.parse, jobicy.parse, workingnomads.parse])
    def test_parsers_tolerate_garbage(self, parser):
        assert parser(None) == []
        assert parser({"unexpected": True}) == []
        assert parser([1, "x", None]) == []


class TestKeywordMatching:

    def record(self, **kw):
        defaults = dict(title="Python Developer", company="Acme", url="u", source="s")
        return JobRecord(**{**defaults, **kw})

    def test_no_keywords_matches_everything(self):
        assert base.matches_keywords(self.record(), [])

    def test_all_words_of_a_keyword_must_appear(self):
        assert base.matches_keywords(self.record(), ["python developer"])
        assert not base.matches_keywords(self.record(), ["python architect"])

    def test_any_keyword_is_enough(self):
        assert base.matches_keywords(self.record(), ["rust", "python"])

    def test_description_is_searched(self):
        assert base.matches_keywords(self.record(description="uses Django"), ["django"])


class TestFetchAndCache:

    def feed(self, monkeypatch, payload):
        calls = []

        def fake(url):
            calls.append(url)
            return payload

        monkeypatch.setattr(base, "fetch_json", fake)
        return calls

    def test_fetch_filters_by_keyword_and_sorts_newest_first(self, monkeypatch):
        self.feed(monkeypatch, REMOTEOK_PAYLOAD)
        records = get_source("remoteok").fetch(["python"])
        assert [r.title for r in records] == ["Senior Python Developer"]

    def test_limit_is_applied(self, monkeypatch):
        self.feed(monkeypatch, REMOTEOK_PAYLOAD)
        assert len(get_source("remoteok").fetch([], limit=1)) == 1
        assert get_source("remoteok").fetch([], limit=0) == []

    def test_second_fetch_uses_cache(self, monkeypatch):
        calls = self.feed(monkeypatch, REMOTEOK_PAYLOAD)
        get_source("remoteok").fetch(["python"])
        get_source("remoteok").fetch(["designer"])
        assert len(calls) == 1

    def test_expired_cache_downloads_again(self, monkeypatch):
        calls = self.feed(monkeypatch, REMOTEOK_PAYLOAD)
        get_source("remoteok").fetch([])
        path = base.cache_path("remoteok")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        data["fetched_at"] = time.time() - 10 * 3600
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        get_source("remoteok").fetch([])
        assert len(calls) == 2

    def test_stale_cache_is_used_when_download_fails(self, monkeypatch):
        self.feed(monkeypatch, REMOTEOK_PAYLOAD)
        get_source("remoteok").fetch([])
        monkeypatch.setenv("SOURCE_CACHE_TTL_SECONDS", "0")

        def boom(url):
            raise ConnectionError("offline")

        monkeypatch.setattr(base, "fetch_json", boom)
        assert len(get_source("remoteok").fetch([])) == 2

    def test_failure_without_cache_raises_source_error(self, monkeypatch):
        def boom(url):
            raise ConnectionError("offline")

        monkeypatch.setattr(base, "fetch_json", boom)
        with pytest.raises(SourceError, match="remotive"):
            get_source("remotive").fetch(["python"])

    def test_remotive_cache_lasts_longer_than_hourly_feeds(self):
        assert get_source("remotive").ttl_seconds >= 6 * 3600
        assert get_source("remotive").ttl_seconds > get_source("remoteok").ttl_seconds

    def test_mock_mode_is_offline_and_cache_free(self, monkeypatch):
        monkeypatch.setenv("MOCK_SEARCH", "true")

        def boom(url):
            raise AssertionError("network used in mock mode")

        monkeypatch.setattr(base, "fetch_json", boom)
        for name in ("remoteok", "remotive", "arbeitnow", "himalayas", "jobicy", "workingnomads"):
            records = get_source(name).fetch(["python"])
            assert len(records) == 2 and records[0].source == name
        assert not os.path.exists(os.path.join(os.environ["DATA_DIR"], "cache"))


class TestRegistry:

    def test_all_sources_registered(self):
        assert available_sources() == [
            "ddg", "remoteok", "remotive", "arbeitnow", "himalayas", "jobicy", "workingnomads", "boards", "web"
        ]

    def test_unknown_source_lists_choices(self):
        with pytest.raises(SourceError, match="available: ddg"):
            get_source("linkedin")

    def test_lookup_ignores_case_and_spaces(self):
        assert get_source(" RemoteOK ") is REGISTRY["remoteok"]

    def test_feed_sources_have_attribution(self):
        for name in ("remoteok", "remotive", "arbeitnow", "himalayas", "jobicy", "workingnomads"):
            assert REGISTRY[name].attribution_url.startswith("https://")


class TestDdgSource:

    def test_fetch_uses_default_sites_when_none_given(self, monkeypatch):
        queries = []
        monkeypatch.setattr(
            ddg,
            "ddg_text",
            lambda q, max_results=10: queries.append(q)
            or [{"title": "T", "href": f"https://x.com/{len(queries)}", "body": "b"}],
        )
        records = ddg.DdgSource().fetch(["python"], limit=100)
        assert len(queries) == len(ddg.DEFAULT_SITES)
        assert all(q.startswith("site:") for q in queries)
        assert len(records) == len(ddg.DEFAULT_SITES)
        assert records[0].source == "ddg"

    def test_fetch_stops_at_limit_and_dedupes_urls(self, monkeypatch):
        monkeypatch.setattr(
            ddg,
            "ddg_text",
            lambda q, max_results=10: [{"title": "T", "href": "https://x.com/same", "body": ""}],
        )
        assert len(ddg.DdgSource().fetch(["python"], limit=5, sites=["a.com", "b.com"])) == 1

    def test_failed_query_is_skipped(self, monkeypatch):
        def boom(q, max_results=10):
            raise RuntimeError("blocked")

        monkeypatch.setattr(ddg, "ddg_text", boom)
        monkeypatch.setattr("jobsieve.util.RETRY_MAX_ATTEMPTS", 1)
        assert ddg.DdgSource().fetch(["python"], sites=["a.com"]) == []

    def test_normalize_site(self):
        assert ddg.normalize_site("https://jobs.lever.co/acme/") == "jobs.lever.co"
        assert ddg.normalize_site("  ") == ""


class TestNormalizeUrl:

    def test_case_trailing_slash_fragment_and_tracking_are_ignored(self):
        a = normalize_url("HTTPS://Example.com/jobs/1/?utm_source=x&ref=y#top")
        assert a == "https://example.com/jobs/1"

    def test_meaningful_query_is_kept(self):
        assert normalize_url("https://stripe.com/jobs/search?gh_jid=8172510") == (
            "https://stripe.com/jobs/search?gh_jid=8172510"
        )

    def test_non_urls_pass_through(self):
        assert normalize_url("not a url") == "not a url"
        assert normalize_url("") == ""


class TestHtmlToText:

    def test_plain_html_is_stripped(self):
        assert base.html_to_text("<p>Hello <b>world</b></p>") == "Hello world"

    def test_entity_encoded_html_is_stripped_too(self):
        encoded = "&lt;div class=&quot;intro&quot;&gt;&lt;h2&gt;About us&lt;/h2&gt;&lt;p&gt;We build&lt;/p&gt;&lt;/div&gt;"
        text = base.html_to_text(encoded)
        assert "<" not in text and ">" not in text
        assert text == "About us We build"

    def test_real_text_with_angle_brackets_is_kept(self):
        assert base.html_to_text("salary < 5000 and > 100") == "salary < 5000 and > 100"

    def test_script_and_style_content_is_dropped(self):
        assert base.html_to_text("<style>p{color:red}</style><script>alert(1)</script><p>Hello</p>") == "Hello"

    def test_empty_values(self):
        assert base.html_to_text(None) == "" and base.html_to_text("") == ""

    def test_length_is_capped(self):
        assert len(base.html_to_text("x" * (base.MAX_DESCRIPTION_CHARS + 500))) == base.MAX_DESCRIPTION_CHARS


class TestWholeWordMatching:

    def record(self, title, description=""):
        return JobRecord(title=title, company="Acme", url="u", source="s", description=description)

    def test_keyword_does_not_match_inside_a_longer_word(self):
        assert not base.matches_keywords(self.record("Senior JavaScript Engineer"), ["java"])
        assert base.matches_keywords(self.record("Senior Java Engineer"), ["java"])

    def test_plurals_still_match(self):
        assert base.matches_keywords(self.record("We hire engineers"), ["engineer"])

    def test_terms_with_symbols_match(self):
        assert base.matches_keywords(self.record("C++ developer"), ["c++"])
        assert base.matches_keywords(self.record("Senior C# / .NET developer"), ["c#"])
        assert not base.matches_keywords(self.record("C developer"), ["c++"])


class TestMojibake:

    def test_double_encoded_text_is_repaired(self):
        broken = "Ù\x85Ø³Ù\x82Ø·".encode("latin-1", errors="ignore") if False else "مسقط".encode("utf-8").decode("latin-1")
        assert base.repair_mojibake(broken) == "مسقط"

    def test_clean_and_unfixable_text_is_left_alone(self):
        assert base.repair_mojibake("Café München") == "Café München"
        assert base.repair_mojibake("â\x80 broken \u2603") == "â\x80 broken \u2603"
        assert base.repair_mojibake(None) == ""

    def test_remoteok_parser_repairs_locations(self):
        payload = [{"position": "Dev", "company": "Acme", "location": "مسقط".encode("utf-8").decode("latin-1"), "url": "u"}]
        assert remoteok.parse(payload)[0].location == "مسقط"
