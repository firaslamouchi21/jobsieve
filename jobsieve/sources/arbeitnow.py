from datetime import datetime, timezone

from . import base
from .base import FeedSource, JobRecord, html_to_text

URL = "https://www.arbeitnow.com/api/job-board-api"


def epoch_to_iso(value) -> str:
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def parse(payload) -> list[JobRecord]:
    rows = payload.get("data") if isinstance(payload, dict) else []
    records = []
    for item in rows or []:
        if not isinstance(item, dict) or not item.get("title"):
            continue
        records.append(
            JobRecord(
                title=str(item["title"]).strip(),
                company=str(item.get("company_name") or "").strip(),
                url=str(item.get("url") or ""),
                source="arbeitnow",
                location=str(item.get("location") or ""),
                remote=bool(item.get("remote")),
                salary="",
                posted_at=epoch_to_iso(item.get("created_at")),
                description=html_to_text(item.get("description")),
            )
        )
    return records


class ArbeitnowSource(FeedSource):
    name = "arbeitnow"
    label = "Arbeitnow"
    attribution_url = "https://www.arbeitnow.com"
    ttl_seconds = 3600.0

    def download(self) -> list[JobRecord]:
        return parse(base.fetch_json(URL))
