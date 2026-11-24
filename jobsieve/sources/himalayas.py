import os

from . import base
from .arbeitnow import epoch_to_iso
from ..util import sleep_delay
from .base import FeedSource, JobRecord, html_to_text

URL = "https://himalayas.app/jobs/api"
PAGE_SIZE = 20
PERIODS = {"annual": "/year", "yearly": "/year", "monthly": "/month", "weekly": "/week", "daily": "/day", "hourly": "/hour"}


def format_salary(item) -> str:
    low, high = item.get("minSalary"), item.get("maxSalary")
    if not (low or high):
        return ""
    amount = f"{low}-{high}" if low and high else str(low or high)
    return " ".join(p for p in (item.get("currency"), amount) if p) + PERIODS.get(item.get("salaryPeriod"), "")


def parse(payload) -> list[JobRecord]:
    jobs = payload.get("jobs") if isinstance(payload, dict) else []
    records = []
    for item in jobs or []:
        if not isinstance(item, dict) or not item.get("title"):
            continue
        restrictions = ", ".join(str(p) for p in item.get("locationRestrictions") or [])
        records.append(
            JobRecord(
                title=str(item["title"]).strip(),
                company=str(item.get("companyName") or "").strip(),
                url=str(item.get("guid") or item.get("applicationLink") or ""),
                source="himalayas",
                location=restrictions,
                restrictions=restrictions,
                remote=True,
                salary=format_salary(item),
                posted_at=epoch_to_iso(item.get("pubDate")),
                expires_at=epoch_to_iso(item.get("expiryDate")),
                description=html_to_text(item.get("description") or item.get("excerpt")),
            )
        )
    return records


class HimalayasSource(FeedSource):
    name = "himalayas"
    label = "Himalayas"
    attribution_url = "https://himalayas.app"
    ttl_seconds = 24 * 3600.0

    def download(self) -> list[JobRecord]:
        pages = max(1, int(os.environ.get("HIMALAYAS_PAGES", "10")))
        records: list[JobRecord] = []
        cursor = ""
        for _ in range(pages):
            query = f"?limit={PAGE_SIZE}" + (f"&cursor={cursor}" if cursor else "")
            payload = base.fetch_json(URL + query)
            records.extend(parse(payload))
            cursor = payload.get("nextCursor") if isinstance(payload, dict) else ""
            if not cursor:
                break
            sleep_delay()
        return records
