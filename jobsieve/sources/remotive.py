from . import base
from .base import FeedSource, JobRecord, html_to_text

URL = "https://remotive.com/api/remote-jobs"


def parse(payload) -> list[JobRecord]:
    jobs = payload.get("jobs") if isinstance(payload, dict) else []
    records = []
    for item in jobs or []:
        if not isinstance(item, dict) or not item.get("title"):
            continue
        records.append(
            JobRecord(
                title=str(item["title"]).strip(),
                company=str(item.get("company_name") or "").strip(),
                url=str(item.get("url") or ""),
                source="remotive",
                location=str(item.get("candidate_required_location") or ""),
                restrictions=str(item.get("candidate_required_location") or ""),
                remote=True,
                salary=str(item.get("salary") or ""),
                posted_at=str(item.get("publication_date") or ""),
                description=html_to_text(item.get("description")),
            )
        )
    return records


class RemotiveSource(FeedSource):
    name = "remotive"
    label = "Remotive"
    attribution_url = "https://remotive.com"
    ttl_seconds = 6 * 3600.0

    def download(self) -> list[JobRecord]:
        return parse(base.fetch_json(URL))
