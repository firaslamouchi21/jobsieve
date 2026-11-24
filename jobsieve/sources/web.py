from .. import crawler, watchlist
from ..util import log_event, mock_enabled
from . import base
from .base import JobRecord, Source, load_feed, matches_keywords

TTL_SECONDS = 12 * 3600.0


class WebSource(Source):
    name = "web"
    label = "Pages you listed"
    attribution_url = ""

    def fetch(self, keywords: list[str], limit: int = 50, **options) -> list[JobRecord]:
        if mock_enabled():
            return []
        fetcher = crawler.PoliteFetcher()
        records: list[JobRecord] = []
        for page in watchlist.load_pages():
            try:
                records.extend(
                    load_feed(f"web-{base.cache_key(page)}", TTL_SECONDS, lambda p=page: crawler.read_jobs(fetcher, p))
                )
            except Exception as error:
                log_event("web_page_failed", url=page, error=str(error)[:140])
        matched = [r for r in records if matches_keywords(r, keywords)]
        matched.sort(key=lambda r: r.posted_at, reverse=True)
        return matched[: max(0, int(limit))]
