import json
import os
import random
import re
import sys
import time
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

REQUEST_DELAY_SECONDS = float(os.environ.get("REQUEST_DELAY_SECONDS", "2.0"))
RETRY_MAX_ATTEMPTS = int(os.environ.get("RETRY_MAX_ATTEMPTS", "5"))
RETRY_BASE_SECONDS = float(os.environ.get("RETRY_BASE_SECONDS", "2.0"))
RETRY_MAX_SECONDS = float(os.environ.get("RETRY_MAX_SECONDS", "16"))

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0",
]


def data_dir() -> str:
    return os.environ.get("DATA_DIR", "./data")


def config_dir() -> str:
    return os.environ.get("CONFIG_DIR", "./config")


def mock_enabled() -> bool:
    return (os.environ.get("MOCK_SEARCH") or "").strip().lower() in ("1", "true", "yes")


def get_random_user_agent():
    return random.choice(USER_AGENTS)


def log_event(event: str, **fields):
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event,
        **fields,
    }
    try:
        sys.stderr.write(json.dumps(payload, ensure_ascii=False) + "\n")
        sys.stderr.flush()
    except Exception:
        pass


def sleep_delay():
    if REQUEST_DELAY_SECONDS > 0:
        time.sleep(REQUEST_DELAY_SECONDS)


def backoff_sleep(attempt: int):
    base = RETRY_BASE_SECONDS * (2 ** max(0, attempt))
    delay = min(RETRY_MAX_SECONDS, base)
    jitter = random.random() * 0.25 * delay
    time.sleep(delay + jitter)


def with_retry(fn):
    last = None
    for attempt in range(RETRY_MAX_ATTEMPTS):
        try:
            return fn()
        except Exception as e:
            last = e
            if attempt < RETRY_MAX_ATTEMPTS - 1:
                log_event(
                    "retry",
                    attempt=attempt + 1,
                    max_attempts=RETRY_MAX_ATTEMPTS,
                    error=str(e),
                )
                backoff_sleep(attempt)
    if last:
        raise last


TRACKING_PARAMS = {"ref", "fbclid", "gclid"}


def normalize_url(url: str) -> str:
    text = (url or "").strip()
    parts = urlsplit(text)
    if not parts.scheme or not parts.netloc:
        return text
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in TRACKING_PARAMS
    ]
    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            parts.path.rstrip("/"),
            urlencode(query),
            "",
        )
    )


def contains_term(text: str, term: str) -> bool:
    wanted = (term or "").strip().lower()
    if not wanted:
        return False
    pattern = r"(?<!\w)" + re.escape(wanted) + r"(?:s|es)?(?!\w)"
    return re.search(pattern, (text or "").lower()) is not None
