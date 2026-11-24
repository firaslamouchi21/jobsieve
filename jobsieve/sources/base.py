import hashlib
import json
import os
import re
import time
from dataclasses import asdict, dataclass

import requests
from bs4 import BeautifulSoup

from ..util import contains_term, data_dir, log_event, mock_enabled

MAX_DESCRIPTION_CHARS = 20000
HTTP_TIMEOUT_SECONDS = 30
CLIENT_USER_AGENT = "jobsieve (+https://github.com/firaslamouchi21/jobsieve)"


class SourceError(Exception):
    pass


@dataclass
class JobRecord:
    title: str
    company: str
    url: str
    source: str
    location: str = ""
    remote: bool | None = None
    salary: str = ""
    posted_at: str = ""
    description: str = ""
    restrictions: str = ""
    expires_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


MOJIBAKE_MARKERS = re.compile(r"[ÃÂÙØâ][\x80-\xbf\u0080-\u00bf]|Ã|â\x80")


def repair_mojibake(text: str | None) -> str:
    value = str(text or "")
    if not MOJIBAKE_MARKERS.search(value):
        return value
    try:
        return value.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value


TAG_PATTERN = re.compile(r"<[a-zA-Z/][^>]*>")


def html_to_text(html: str | None) -> str:
    if not html:
        return ""
    text = str(html)
    for _ in range(2):
        soup = BeautifulSoup(text, "html.parser")
        for tag in soup(["script", "style"]):
            tag.decompose()
        text = soup.get_text(" ", strip=True)
        if not TAG_PATTERN.search(text):
            break
    return text[:MAX_DESCRIPTION_CHARS]


def matches_keywords(record: JobRecord, keywords: list[str]) -> bool:
    wanted = [k.strip().lower() for k in keywords or [] if k and k.strip()]
    if not wanted:
        return True
    haystack = f"{record.title} {record.company} {record.description}"
    return any(all(contains_term(haystack, word) for word in kw.split()) for kw in wanted)


def fetch_json(url: str):
    response = requests.get(
        url, timeout=HTTP_TIMEOUT_SECONDS, headers={"User-Agent": CLIENT_USER_AGENT}
    )
    response.raise_for_status()
    return response.json()


def cache_key(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def cache_path(name: str) -> str:
    return os.path.join(data_dir(), "cache", f"{name}.json")


def cache_ttl(default_seconds: float) -> float:
    override = (os.environ.get("SOURCE_CACHE_TTL_SECONDS") or "").strip()
    return float(override) if override else default_seconds


def read_cache(name: str) -> tuple[float, list[JobRecord]] | None:
    try:
        with open(cache_path(name), "r", encoding="utf-8") as f:
            data = json.load(f)
        return float(data["fetched_at"]), [JobRecord(**row) for row in data["records"]]
    except Exception:
        return None


def write_cache(name: str, records: list[JobRecord]):
    path = cache_path(name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(
            {"fetched_at": time.time(), "records": [r.to_dict() for r in records]}, f
        )
    os.replace(tmp_path, path)


def load_feed(name: str, ttl_seconds: float, download, on_removed=None) -> list[JobRecord]:
    cached = read_cache(name)
    if cached and time.time() - cached[0] < cache_ttl(ttl_seconds):
        return cached[1]
    try:
        records = download()
    except Exception as error:
        if cached:
            log_event("source_stale_cache_used", source=name, error=str(error)[:120])
            return cached[1]
        raise SourceError(f"{name}: {type(error).__name__}: {str(error)[:120]}") from error
    write_cache(name, records)
    if on_removed and cached and records:
        try:
            on_removed(cached[1], records)
        except Exception as error:
            log_event("closed_check_failed", source=name, error=str(error)[:120])
    return records


class Source:
    name = ""
    label = ""
    attribution_url = ""
    has_full_text = True

    def fetch(self, keywords: list[str], limit: int = 50, **options) -> list[JobRecord]:
        raise NotImplementedError


class FeedSource(Source):
    ttl_seconds = 3600.0

    def download(self) -> list[JobRecord]:
        raise NotImplementedError

    def mock_records(self) -> list[JobRecord]:
        return [
            JobRecord(
                title=f"Mock Python Developer {i}",
                company=f"Mock Company {i}",
                url=f"https://example.com/{self.name}/{i}",
                source=self.name,
                location="Remote",
                remote=True,
                salary="",
                posted_at=f"2026-01-0{i}T00:00:00+00:00",
                description="python developer backend remote mock listing",
            )
            for i in (1, 2)
        ]

    def fetch(self, keywords: list[str], limit: int = 50, **options) -> list[JobRecord]:
        if mock_enabled():
            records = self.mock_records()
        else:
            records = load_feed(self.name, self.ttl_seconds, self.download)
        matched = [r for r in records if matches_keywords(r, keywords)]
        matched.sort(key=lambda r: r.posted_at, reverse=True)
        return matched[: max(0, int(limit))]
