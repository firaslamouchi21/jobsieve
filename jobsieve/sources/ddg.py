import os
from urllib.parse import urlparse

from ddgs import DDGS

from ..util import log_event, mock_enabled, sleep_delay, with_retry
from .base import JobRecord, Source

SEARCH_BACKENDS = ("auto", "duckduckgo", "bing")

DEFAULT_SITES = (
    "boards.greenhouse.io",
    "jobs.lever.co",
    "jobs.ashbyhq.com",
    "apply.workable.com",
    "jobs.smartrecruiters.com",
    "weworkremotely.com",
    "remoteok.com",
    "wellfound.com",
)


def default_sites() -> list[str]:
    configured = [
        x.strip() for x in (os.environ.get("DEFAULT_SITES") or "").split(",") if x.strip()
    ]
    return configured or list(DEFAULT_SITES)


def normalize_site(site: str) -> str:
    s = (site or "").strip()
    if not s:
        return ""
    if "://" in s:
        try:
            p = urlparse(s)
            s = p.netloc or p.path or s
        except Exception:
            pass
    s = s.strip().strip("/")
    if "/" in s:
        s = s.split("/", 1)[0]
    return s


def build_query(site: str, keyword: str) -> str:
    site_norm = normalize_site(site)
    return " ".join(x for x in [f"site:{site_norm}" if site_norm else "", keyword] if x)


def ddg_text(query: str, max_results: int = 10):
    if mock_enabled():
        return [
            {
                "title": "Mock Job",
                "href": "https://example.com/job",
                "body": f"mock snippet for {query}",
            }
        ]
    last = None
    for backend in SEARCH_BACKENDS:
        try:
            with DDGS() as ddgs:
                return list(ddgs.text(query, max_results=max_results, backend=backend))
        except Exception as e:
            last = e
    if last:
        raise last
    return []


class DdgSource(Source):
    name = "ddg"
    label = "Web search (DuckDuckGo)"
    attribution_url = "https://duckduckgo.com"
    has_full_text = False

    def search(self, site: str, keyword: str, limit: int = 10) -> list[JobRecord]:
        query = build_query(site, keyword)

        def run():
            sleep_delay()
            return ddg_text(query, max_results=limit)

        site_norm = normalize_site(site)
        return [
            JobRecord(
                title=row.get("title") or "",
                company=site_norm,
                url=row.get("href") or "",
                source=self.name,
                description=row.get("body") or "",
            )
            for row in with_retry(run)
        ]

    def fetch(
        self,
        keywords: list[str],
        limit: int = 50,
        sites: list[str] | None = None,
        **options,
    ) -> list[JobRecord]:
        chosen = [s for s in (sites or []) if normalize_site(s)] or default_sites()
        found: list[JobRecord] = []
        seen: set[str] = set()
        for site in chosen:
            for keyword in keywords or [""]:
                try:
                    rows = self.search(site, keyword)
                except Exception:
                    log_event("search_failed", query=build_query(site, keyword))
                    continue
                for record in rows:
                    if record.url and record.url not in seen:
                        seen.add(record.url)
                        found.append(record)
                if len(found) >= limit:
                    return found[:limit]
        return found
