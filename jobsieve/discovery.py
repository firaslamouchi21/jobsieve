from urllib.parse import parse_qs, urlsplit

from . import watchlist
from .util import log_event

BOARD_HOSTS = {
    "boards.greenhouse.io": "greenhouse",
    "job-boards.greenhouse.io": "greenhouse",
    "jobs.lever.co": "lever",
    "jobs.ashbyhq.com": "ashby",
    "jobs.smartrecruiters.com": "smartrecruiters",
    "careers.smartrecruiters.com": "smartrecruiters",
}
NOT_COMPANIES = {"embed", "api", "v1", "static", "assets"}


def board_from_url(url: str) -> tuple[str, str] | None:
    try:
        parts = urlsplit(str(url or ""))
    except ValueError:
        return None
    board = BOARD_HOSTS.get((parts.hostname or "").lower())
    if not board:
        return None
    segments = [s for s in parts.path.split("/") if s]
    slug = (parse_qs(parts.query).get("for") or [""])[0] if segments[:1] == ["embed"] else (segments[0] if segments else "")
    if not slug or slug.lower() in NOT_COMPANIES or not watchlist.SLUG.match(slug):
        return None
    return board, slug


def learn(urls) -> int:
    added = 0
    for url in urls:
        found = board_from_url(url)
        if not found:
            continue
        try:
            if watchlist.add(found[0], found[1], added_by="discovered"):
                added += 1
        except watchlist.WatchlistError as error:
            log_event("discovery_skipped", error=str(error)[:120])
            break
    if added:
        log_event("companies_discovered", count=added)
    return added


def search(keywords: list[str], places: list[str] | None = None, sites=None, limit: int = 10) -> int:
    from .sources.ddg import DdgSource, default_sites

    source = DdgSource()
    found = 0
    for site in sites or [h for h in default_sites() if h in BOARD_HOSTS]:
        for keyword in keywords:
            for place in places or [""]:
                records = source.search(site, f"{keyword} {place}".strip(), limit=limit)
                found += learn(r.url for r in records)
    return found
