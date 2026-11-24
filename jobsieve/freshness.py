from datetime import datetime, timezone

NEW_DAYS = 3
RECENT_DAYS = 14
OLD_DAYS = 45


def parse(value) -> datetime | None:
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def assess(job: dict, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    posted, seen, expires, closed = (parse(job.get(k)) for k in ("posted_at", "created_at", "expires_at", "closed_at"))
    facts = []
    if posted:
        facts.append(f"posted {plural(max(0, (now - posted).days), 'day')} ago")
    if seen:
        facts.append(f"first seen {plural(max(0, (now - seen).days), 'day')} ago")
    if int(job.get("repost_count") or 0):
        facts.append(f"reposted {plural(int(job['repost_count']), 'time')}")
    if expires:
        left = (expires - now).days
        facts.append(f"closes in {plural(left, 'day')}" if expires > now else "past its stated closing date")
    if closed:
        facts.append("no longer listed by its source")
        return {"label": "closed", "facts": facts}
    if expires and expires <= now:
        return {"label": "closed", "facts": facts}
    reference = posted or seen
    if not reference:
        return {"label": "unknown", "facts": facts}
    age = max(0, (now - reference).days)
    label = "new" if age <= NEW_DAYS else "recent" if age <= RECENT_DAYS else "old" if age <= OLD_DAYS else "stale"
    return {"label": label, "facts": facts}
