from datetime import datetime, timezone

from .. import db, watchlist
from ..util import log_event, mock_enabled, sleep_delay
from . import base
from .base import JobRecord, Source, html_to_text, load_feed, matches_keywords

TTL_SECONDS = 6 * 3600.0
GREENHOUSE = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
LEVER = "https://api.lever.co/v0/postings/{slug}?mode=json"
ASHBY = "https://api.ashbyhq.com/posting-api/job-board/{slug}"
SMARTRECRUITERS_LIMIT = 100
SMARTRECRUITERS = "https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100"
SMARTRECRUITERS_PAGE = "https://jobs.smartrecruiters.com/{slug}/{id}"


def ms_to_iso(value) -> str:
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def parse_greenhouse(payload, slug: str) -> list[JobRecord]:
    records = []
    for item in (payload.get("jobs") if isinstance(payload, dict) else None) or []:
        if not isinstance(item, dict) or not item.get("title"):
            continue
        location = item.get("location") if isinstance(item.get("location"), dict) else {}
        records.append(
            JobRecord(
                title=str(item["title"]).strip(),
                company=str(item.get("company_name") or slug),
                url=str(item.get("absolute_url") or ""),
                source="greenhouse",
                location=str(location.get("name") or ""),
                posted_at=str(item.get("first_published") or item.get("updated_at") or ""),
                description=html_to_text(item.get("content")),
                expires_at=str(item.get("application_deadline") or ""),
            )
        )
    return records


def parse_lever(payload, slug: str) -> list[JobRecord]:
    records = []
    for item in payload if isinstance(payload, list) else []:
        if not isinstance(item, dict) or not item.get("text"):
            continue
        categories = item.get("categories") if isinstance(item.get("categories"), dict) else {}
        mode = str(item.get("workplaceType") or "").lower()
        records.append(
            JobRecord(
                title=str(item["text"]).strip(),
                company=slug,
                url=str(item.get("hostedUrl") or ""),
                source="lever",
                location=str(categories.get("location") or ""),
                remote={"remote": True, "onsite": False, "on-site": False}.get(mode),
                posted_at=ms_to_iso(item.get("createdAt")),
                description=str(item.get("descriptionPlain") or html_to_text(item.get("description"))),
            )
        )
    return records


def parse_ashby(payload, slug: str) -> list[JobRecord]:
    records = []
    for item in (payload.get("jobs") if isinstance(payload, dict) else None) or []:
        if not isinstance(item, dict) or not item.get("title") or item.get("isListed") is False:
            continue
        records.append(
            JobRecord(
                title=str(item["title"]).strip(),
                company=slug,
                url=str(item.get("jobUrl") or ""),
                source="ashby",
                location=str(item.get("location") or ""),
                remote=item["isRemote"] if isinstance(item.get("isRemote"), bool) else None,
                posted_at=str(item.get("publishedAt") or ""),
                description=str(item.get("descriptionPlain") or html_to_text(item.get("descriptionHtml"))),
            )
        )
    return records


def parse_smartrecruiters(payload, slug: str) -> list[JobRecord]:
    records = []
    for item in (payload.get("content") if isinstance(payload, dict) else None) or []:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        place = item.get("location") if isinstance(item.get("location"), dict) else {}
        company = item.get("company") if isinstance(item.get("company"), dict) else {}
        extras = [
            (item.get(key) or {}).get("label", "")
            for key in ("department", "function", "industry")
            if isinstance(item.get(key), dict)
        ]
        records.append(
            JobRecord(
                title=str(item["name"]).strip(),
                company=str(company.get("name") or slug),
                url=SMARTRECRUITERS_PAGE.format(slug=slug, id=item.get("id", "")),
                source="smartrecruiters",
                location=str(place.get("fullLocation") or ""),
                remote=place["remote"] if isinstance(place.get("remote"), bool) else None,
                posted_at=str(item.get("releasedDate") or ""),
                description=" / ".join(x for x in extras if x),
            )
        )
    return records


BOARD_PARSERS = {
    "greenhouse": (GREENHOUSE, parse_greenhouse),
    "lever": (LEVER, parse_lever),
    "ashby": (ASHBY, parse_ashby),
    "smartrecruiters": (SMARTRECRUITERS, parse_smartrecruiters),
}


def fetch_board(board: str, slug: str) -> list[JobRecord]:
    url, parser = BOARD_PARSERS[board]
    return parser(base.fetch_json(url.format(slug=slug)), slug)


def close_removed(board: str, before: list[JobRecord], after: list[JobRecord]) -> None:
    if board == "smartrecruiters" and len(after) >= SMARTRECRUITERS_LIMIT:
        return
    gone = {r.url for r in before} - {r.url for r in after}
    if gone:
        count = db.mark_closed(gone)
        log_event("jobs_closed", board=board, count=count)


class BoardsSource(Source):
    name = "boards"
    label = "Company career boards"
    attribution_url = ""

    def mock_records(self) -> list[JobRecord]:
        return [
            JobRecord(
                title=f"Mock Python Developer {i}",
                company=f"Mock Company {i}",
                url=f"https://example.com/boards/{i}",
                source="greenhouse",
                location="Dubai, United Arab Emirates",
                posted_at=f"2026-01-0{i}T00:00:00+00:00",
                description="python developer backend mock listing",
            )
            for i in (1, 2)
        ]

    def fetch(self, keywords: list[str], limit: int = 50, **options) -> list[JobRecord]:
        if mock_enabled():
            records = self.mock_records()
        else:
            records = []
            for entry in watchlist.load():
                name = f"board-{entry['board']}-{entry['slug'].lower()}"
                try:
                    records.extend(
                        load_feed(
                            name, TTL_SECONDS, lambda e=entry: self._download(e),
                            on_removed=lambda before, after, e=entry: close_removed(e["board"], before, after),
                        )
                    )
                except Exception as error:
                    log_event("board_failed", board=entry["board"], company=entry["slug"], error=str(error)[:120])
        matched = [r for r in records if matches_keywords(r, keywords)]
        matched.sort(key=lambda r: r.posted_at, reverse=True)
        return matched[: max(0, int(limit))]

    def _download(self, entry: dict) -> list[JobRecord]:
        try:
            return fetch_board(entry["board"], entry["slug"])
        finally:
            sleep_delay()
