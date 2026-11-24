from . import base
from .base import FeedSource, JobRecord, html_to_text, repair_mojibake

URL = "https://remoteok.com/api"


def salary_text(item: dict) -> str:
    low = int(item.get("salary_min") or 0)
    high = int(item.get("salary_max") or 0)
    if low and high:
        return f"{low}-{high}"
    return str(low or high or "")


def parse(payload) -> list[JobRecord]:
    records = []
    for item in payload if isinstance(payload, list) else []:
        if not isinstance(item, dict) or not item.get("position"):
            continue
        records.append(
            JobRecord(
                title=repair_mojibake(str(item["position"])).strip(),
                company=repair_mojibake(str(item.get("company") or "")).strip(),
                url=str(item.get("url") or item.get("apply_url") or ""),
                source="remoteok",
                location=repair_mojibake(str(item.get("location") or "")),
                remote=True,
                salary=salary_text(item),
                posted_at=str(item.get("date") or ""),
                description=html_to_text(repair_mojibake(item.get("description"))),
            )
        )
    return records


class RemoteOkSource(FeedSource):
    name = "remoteok"
    label = "Remote OK"
    attribution_url = "https://remoteok.com"
    ttl_seconds = 3600.0

    def download(self) -> list[JobRecord]:
        return parse(base.fetch_json(URL))
