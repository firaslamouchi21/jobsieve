from . import base
from .base import FeedSource, JobRecord, html_to_text

URL = "https://jobicy.com/api/v2/remote-jobs?count=100"
PERIODS = {"yearly": "/year", "monthly": "/month", "weekly": "/week", "daily": "/day", "hourly": "/hour"}


def format_salary(item) -> str:
    low, high = item.get("salaryMin"), item.get("salaryMax")
    if not (low or high):
        return ""
    amount = f"{low}-{high}" if low and high else str(low or high)
    return " ".join(p for p in (item.get("salaryCurrency"), amount) if p) + PERIODS.get(item.get("salaryPeriod"), "")


def clean_geo(value) -> str:
    return ", ".join(part.strip() for part in str(value or "").split(",") if part.strip())


def parse(payload) -> list[JobRecord]:
    jobs = payload.get("jobs") if isinstance(payload, dict) else []
    records = []
    for item in jobs or []:
        if not isinstance(item, dict) or not item.get("jobTitle"):
            continue
        geo = clean_geo(item.get("jobGeo"))
        records.append(
            JobRecord(
                title=html_to_text(item["jobTitle"]),
                company=html_to_text(item.get("companyName")),
                url=str(item.get("url") or ""),
                source="jobicy",
                location=geo,
                restrictions=geo,
                remote=True,
                salary=format_salary(item),
                posted_at=str(item.get("pubDate") or ""),
                description=html_to_text(item.get("jobDescription") or item.get("jobExcerpt")),
            )
        )
    return records


class JobicySource(FeedSource):
    name = "jobicy"
    label = "Jobicy"
    attribution_url = "https://jobicy.com"
    ttl_seconds = 3600.0

    def download(self) -> list[JobRecord]:
        return parse(base.fetch_json(URL))
