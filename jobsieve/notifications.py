import logging
import os
import smtplib
import requests
from email.mime.text import MIMEText
from datetime import datetime, timezone

logger = logging.getLogger("jobsieve.notifications")

NOTIFICATION_WEBHOOK = os.environ.get("NOTIFICATION_WEBHOOK", "")
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT") or "587")
EMAIL_USER = os.environ.get("EMAIL_USER", "")
EMAIL_PASS = os.environ.get("EMAIL_PASS", "")
EMAIL_TO = os.environ.get("EMAIL_TO", "")
MIN_SCORE_NOTIFY = int(os.environ.get("MIN_SCORE_NOTIFY") or "7")

def get_last_check():
    from . import db

    return db.get_meta("last_check", "1970-01-01T00:00:00")


def set_last_check(ts: str):
    from . import db

    db.set_meta("last_check", ts)


def verdict_label(job: dict) -> str:
    return {"eligible": "eligible", "unknown": "unclear", "not_eligible": "not eligible"}.get(job.get("eligibility") or "", "not checked yet")


def render_markdown(jobs: list, limit: int = 10) -> str:
    lines = [f"**{len(jobs)} new matches**", ""]
    for j in jobs[:limit]:
        place = f" · {j['location']}" if j.get("location") else ""
        lines.append(f"- [{j['title']}]({j['link']}) · {j.get('company') or ''}{place} · score {j.get('score') or 0}/10 · {verdict_label(j)}")
    if len(jobs) > limit:
        lines.append(f"- and {len(jobs) - limit} more")
    return "\n".join(lines)


def webhook_payload(url: str, jobs: list) -> dict:
    text = render_markdown(jobs, 5)
    host = url.split("/")[2] if "://" in url else ""
    if host.endswith("slack.com"):
        return {"text": text}
    if host.endswith("discord.com") or host.endswith("discordapp.com"):
        return {"content": text[:1900]}
    return {
        "text": f"Found {len(jobs)} new matching jobs!",
        "jobs": [
            {"title": j["title"], "score": j["score"], "link": j["link"], "eligibility": j.get("eligibility")}
            for j in jobs[:5]
        ],
    }


def telegram_configured() -> bool:
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"))


def send_telegram(jobs: list):
    if not telegram_configured():
        return False
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/sendMessage",
            json={"chat_id": os.environ["TELEGRAM_CHAT_ID"], "text": render_markdown(jobs).replace("**", ""), "disable_web_page_preview": True},
            timeout=15,
        )
        response.raise_for_status()
        return True
    except Exception as error:
        logger.warning("telegram notification failed: %s", type(error).__name__)
        return False


def send_webhook(jobs: list):
    if not NOTIFICATION_WEBHOOK:
        return False
    payload = webhook_payload(NOTIFICATION_WEBHOOK, jobs)
    try:
        response = requests.post(
            NOTIFICATION_WEBHOOK,
            json=payload,
            timeout=15,
            headers={"Content-Type": "application/json"},
        )
        response.raise_for_status()
        return True
    except Exception as error:
        logger.warning("webhook notification failed: %s", type(error).__name__)
        return False


def send_email(jobs: list):
    if not email_configured():
        return False
    subject = f"Job Alert: {len(jobs)} new matches found"
    body = "New job matches:\n\n"
    for j in jobs[:10]:
        body += f"• {j['title']} (Score: {j['score']}, {verdict_label(j)})\n  {j['link']}\n\n"
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = EMAIL_USER
    msg["To"] = EMAIL_TO
    try:
        with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT) as s:
            s.starttls()
            s.login(EMAIL_USER, EMAIL_PASS)
            s.send_message(msg)
        return True
    except Exception as error:
        logger.warning("email notification failed: %s", type(error).__name__)
        return False


def email_configured() -> bool:
    return all([EMAIL_HOST, EMAIL_USER, EMAIL_PASS, EMAIL_TO])


def alerts_configured() -> bool:
    return bool(NOTIFICATION_WEBHOOK) or email_configured() or telegram_configured()


def pending_matches() -> list:
    from . import db

    return [j for j in db.get_jobs_since(get_last_check()) if (j.get("score") or 0) >= MIN_SCORE_NOTIFY]


def check_and_notify():
    high_score = pending_matches()
    checked_at = datetime.now(timezone.utc).isoformat()
    if not high_score:
        set_last_check(checked_at)
        return 0
    delivered = [send_webhook(high_score), send_email(high_score), send_telegram(high_score)]
    if any(delivered) or not alerts_configured():
        set_last_check(checked_at)
    return len(high_score)
