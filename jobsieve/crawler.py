import json
import re
import time
from urllib import robotparser
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

from .careers import CareerPageError, check_public_url
from .sources.base import CLIENT_USER_AGENT, HTTP_TIMEOUT_SECONDS, JobRecord, html_to_text
from .util import REQUEST_DELAY_SECONDS, log_event

MAX_PAGE_BYTES = 3_000_000
MAX_DETAIL_PAGES = 25
MIN_DELAY_SECONDS = 2.0
JOB_LINK = re.compile(r"/(jobs?|vacanc(?:y|ies)|careers?|positions?|openings?|opportunit(?:y|ies))/[^/?#]+", re.I)
CHALLENGE_MARKERS = ("captcha", "cf-chl", "challenge-platform", "are you a robot", "unusual traffic", "access denied", "verify you are human")


REFUSED_NAMES = ("linkedin", "indeed", "glassdoor")


def refused_site(url: str) -> str:
    labels = (urlsplit(url).hostname or "").lower().split(".")
    return next((name for name in REFUSED_NAMES if name in labels), "")


class BotChallenge(CareerPageError):
    pass


class PoliteFetcher:

    def __init__(self, sleep=time.sleep, clock=time.monotonic):
        self.sleep, self.clock = sleep, clock
        self.robots: dict[str, robotparser.RobotFileParser | None] = {}
        self.last_request: dict[str, float] = {}
        self.stopped: set[str] = set()
        self.delay = max(MIN_DELAY_SECONDS, REQUEST_DELAY_SECONDS)

    def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        host = parts.netloc
        if host not in self.robots:
            parser = robotparser.RobotFileParser()
            try:
                response = requests.get(
                    f"{parts.scheme}://{host}/robots.txt", timeout=HTTP_TIMEOUT_SECONDS,
                    headers={"User-Agent": CLIENT_USER_AGENT}, allow_redirects=False,
                )
                if response.status_code in (401, 403):
                    parser = None
                elif response.status_code < 400:
                    parser.parse(response.text.splitlines())
                else:
                    parser.parse([])
            except requests.RequestException:
                parser.parse([])
            self.robots[host] = parser
        parser = self.robots[host]
        return parser is not None and parser.can_fetch(CLIENT_USER_AGENT, url)

    def wait_turn(self, host: str):
        last = self.last_request.get(host)
        if last is not None:
            remaining = self.delay - (self.clock() - last)
            if remaining > 0:
                self.sleep(remaining)
        self.last_request[host] = self.clock()

    def get(self, url: str) -> str:
        checked = check_public_url(url)
        host = urlsplit(checked).netloc
        if refused_site(checked):
            raise CareerPageError(f"{host}: its terms forbid automated reading; use the browser extension on a page you open yourself")
        if host in self.stopped:
            raise BotChallenge(f"{host}: stopped after a bot check")
        if not self.allowed(checked):
            raise CareerPageError(f"{host}: robots.txt does not allow reading {urlsplit(checked).path or '/'}")
        self.wait_turn(host)
        try:
            response = requests.get(
                checked, timeout=HTTP_TIMEOUT_SECONDS, headers={"User-Agent": CLIENT_USER_AGENT},
                stream=True, allow_redirects=False,
            )
            if response.is_redirect and response.headers.get("Location"):
                target = urljoin(checked, response.headers["Location"])
                response.close()
                if urlsplit(check_public_url(target)).netloc != host:
                    raise CareerPageError(f"{host}: redirected to another site")
                return self.get(target)
            body = response.raw.read(MAX_PAGE_BYTES + 1, decode_content=True)[:MAX_PAGE_BYTES]
        except requests.RequestException as error:
            raise CareerPageError(f"{host}: cannot read the page ({str(error)[:80]})") from error
        text = body.decode(response.encoding or "utf-8", errors="replace")
        if response.status_code in (403, 429, 503) or self.looks_like_challenge(text):
            self.stopped.add(host)
            log_event("crawler_bot_check", host=host, status=response.status_code)
            raise BotChallenge(f"{host}: answered with a bot check (status {response.status_code}); stopped for this run")
        if response.status_code >= 400:
            raise CareerPageError(f"{host}: status {response.status_code}")
        return text

    @staticmethod
    def looks_like_challenge(text: str) -> bool:
        head = text[:6000].lower()
        return len(text) < 20000 and any(marker in head for marker in CHALLENGE_MARKERS)


def json_ld_blocks(html: str) -> list:
    blocks = []
    for tag in BeautifulSoup(html, "html.parser").find_all("script", type="application/ld+json"):
        try:
            blocks.append(json.loads(tag.string or tag.get_text() or ""))
        except ValueError:
            continue
    return blocks


def job_postings(node) -> list[dict]:
    found = []
    if isinstance(node, list):
        for item in node:
            found.extend(job_postings(item))
    elif isinstance(node, dict):
        kind = node.get("@type")
        kinds = kind if isinstance(kind, list) else [kind]
        if "JobPosting" in kinds:
            found.append(node)
        for key in ("@graph", "itemListElement", "item"):
            if key in node:
                found.extend(job_postings(node[key]))
    return found


def name_of(value) -> str:
    if isinstance(value, str):
        return value
    return str(value.get("name") or "") if isinstance(value, dict) else ""


def place_of(place) -> str:
    address = place.get("address") if isinstance(place, dict) else None
    if isinstance(address, str):
        return address
    if not isinstance(address, dict):
        return name_of(place)
    parts = [address.get("addressLocality"), address.get("addressRegion"), name_of(address.get("addressCountry"))]
    return ", ".join(str(p) for p in parts if p)


def as_list(value) -> list:
    return value if isinstance(value, list) else [] if value is None else [value]


def record_from_posting(posting: dict, page_url: str, source: str) -> JobRecord | None:
    title = str(posting.get("title") or "").strip()
    if not title:
        return None
    required = ", ".join(n for n in (name_of(r) for r in as_list(posting.get("applicantLocationRequirements"))) if n)
    return JobRecord(
        title=title,
        company=name_of(posting.get("hiringOrganization")).strip(),
        url=str(posting.get("url") or page_url),
        source=source,
        location=" / ".join(p for p in (place_of(x) for x in as_list(posting.get("jobLocation"))) if p),
        remote=True if str(posting.get("jobLocationType") or "").upper() == "TELECOMMUTE" else None,
        posted_at=str(posting.get("datePosted") or ""),
        expires_at=str(posting.get("validThrough") or ""),
        description=html_to_text(posting.get("description")),
        restrictions=required,
    )


def detail_links(html: str, page_url: str) -> list[str]:
    host = urlsplit(page_url).netloc
    links = []
    for anchor in BeautifulSoup(html, "html.parser").find_all("a", href=True):
        target = urljoin(page_url, anchor["href"]).split("#")[0]
        parts = urlsplit(target)
        if parts.netloc == host and target != page_url and JOB_LINK.search(parts.path) and target not in links:
            links.append(target)
    return links


def read_jobs(fetcher: PoliteFetcher, url: str, source: str = "web") -> list[JobRecord]:
    html = fetcher.get(url)
    postings = [p for block in json_ld_blocks(html) for p in job_postings(block)]
    records = [r for r in (record_from_posting(p, url, source) for p in postings) if r]
    if records:
        return records
    for link in detail_links(html, url)[:MAX_DETAIL_PAGES]:
        try:
            detail = fetcher.get(link)
        except BotChallenge:
            raise
        except CareerPageError as error:
            log_event("crawler_page_skipped", url=link, error=str(error)[:100])
            continue
        records.extend(
            r for r in (record_from_posting(p, link, source) for b in json_ld_blocks(detail) for p in job_postings(b)) if r
        )
    return records
