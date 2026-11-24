import os
import threading

from . import scraper
from .util import log_event

KEY_NAMES = {"groq": "GROQ_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "gemini": "GEMINI_API_KEY"}


def run_once() -> bool:
    if not scraper.try_lock():
        log_event("scheduled_run_skipped", reason="already_running")
        return False
    provider = (os.environ.get("SCHEDULE_PROVIDER") or "groq").strip().lower()
    has_key = bool((os.environ.get(KEY_NAMES.get(provider, "")) or "").strip())
    scraper.run_scrape("", not has_key, provider=provider, _lock_acquired=True)
    return True


def interval_seconds(hours) -> float:
    try:
        value = float(hours)
    except (TypeError, ValueError):
        return 0.0
    return max(0.25, value) * 3600 if value > 0 else 0.0


def loop(hours, stop: threading.Event | None = None) -> None:
    stop = stop or threading.Event()
    seconds = interval_seconds(hours)
    if not seconds:
        return
    while not stop.is_set():
        try:
            run_once()
        except Exception as error:
            log_event("scheduled_run_failed", error=str(error)[:160])
        if stop.wait(seconds):
            break


def start_from_environment() -> threading.Thread | None:
    if not interval_seconds(os.environ.get("RUN_EVERY_HOURS")):
        return None
    thread = threading.Thread(target=loop, args=(os.environ["RUN_EVERY_HOURS"],), daemon=True, name="jobsieve-schedule")
    thread.start()
    log_event("schedule_started", every_hours=os.environ["RUN_EVERY_HOURS"])
    return thread
