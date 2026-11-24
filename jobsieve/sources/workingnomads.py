from . import base
from .base import FeedSource, JobRecord, html_to_text

URL = "https://www.workingnomads.com/api/exposed_jobs/"


def parse(payload) -> list[JobRecord]:
    records = []
    for item in payload if isinstance(payload, list) else []:
        if not isinstance(item, dict) or not item.get("title"):
            continue
        location = str(item.get("location") or "").strip()
        records.append(
            JobRecord(
                title=str(item["title"]).strip(),
                company=str(item.get("company_name") or "").strip(),
                url=str(item.get("url") or ""),
                source="workingnomads",
                location=location,
                restrictions=location,
                remote=True,
                posted_at=str(item.get("pub_date") or ""),
                description=html_to_text(item.get("description")),
            )
        )
    return records


class WorkingNomadsSource(FeedSource):
    name = "workingnomads"
    label = "Working Nomads"
    attribution_url = "https://www.workingnomads.com"
    ttl_seconds = 3600.0

    def download(self) -> list[JobRecord]:
        return parse(base.fetch_json(URL))
