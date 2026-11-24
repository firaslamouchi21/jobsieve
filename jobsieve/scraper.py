import hashlib
import json
import os
import threading
import time
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from . import db, discovery, eligibility
from . import profile as prof
from .ai_service import AIService, is_ai_failure
from .sources import DEFAULT_SOURCES, SourceError, get_source
from .sources.ddg import build_query, default_sites, normalize_site
from .util import (
    config_dir,
    data_dir,
    get_random_user_agent,
    log_event,
    sleep_delay,
    with_retry,
)

USE_PLAYWRIGHT = os.environ.get("USE_PLAYWRIGHT", "true").lower() == "true"
LOCK_STALE_SECONDS = float(os.environ.get("LOCK_STALE_SECONDS", "900"))

_pause_requested = False
_stop_requested = False


def __getattr__(name):
    if name == "api":
        from .api import api

        return api
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def status_path() -> str:
    return os.path.join(data_dir(), "status.json")


def log_path() -> str:
    return os.path.join(data_dir(), "scraper.log")


def lock_path() -> str:
    return os.path.join(data_dir(), "run.lock")


def read_lines(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return [x.strip() for x in f.read().splitlines() if x.strip()]
    except Exception:
        return []


def read_text(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


def write_status(message: str, progress: int, meta: dict | None = None):
    os.makedirs(data_dir(), exist_ok=True)
    payload = {
        "message": message,
        "progress": int(progress),
        "timestamp": time.time(),
    }
    if meta:
        payload.update(meta)
    tmp_path = status_path() + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        os.replace(tmp_path, status_path())
    except Exception:
        pass
    touch_lock()


def append_log(line: str):
    os.makedirs(data_dir(), exist_ok=True)
    try:
        with open(log_path(), "a", encoding="utf-8") as f:
            f.write(f"{datetime.now(timezone.utc).isoformat()} {line}\n")
    except Exception:
        pass


def read_lock():
    try:
        with open(lock_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def pid_is_alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except Exception:
        return True
    return True


def lock_is_stale() -> bool:
    if not os.path.exists(lock_path()):
        return False
    data = read_lock()
    pid = data.get("pid")
    if pid is not None and not pid_is_alive(pid):
        return True
    try:
        last_beat = float(data.get("heartbeat") or os.path.getmtime(lock_path()))
    except Exception:
        return False
    return time.time() - last_beat > LOCK_STALE_SECONDS


def is_running():
    return os.path.exists(lock_path()) and not lock_is_stale()


def recover_from_crash():
    unlock()
    try:
        with open(status_path(), "r", encoding="utf-8") as f:
            previous = json.load(f)
    except Exception:
        return
    if previous.get("running"):
        write_status(
            "interrupted",
            int(previous.get("progress", 0) or 0),
            {"running": False, "added": previous.get("added", 0), "paused": False},
        )
        log_event("run_interrupted_recovered")


def is_paused():
    return _pause_requested

def pause_requested():
    return _pause_requested

def stop_requested():
    return _stop_requested

def request_pause():
    global _pause_requested
    _pause_requested = True

def request_resume():
    global _pause_requested
    _pause_requested = False

def request_stop():
    global _stop_requested
    _stop_requested = True


_run_lock = threading.Lock()


def write_lock(started_at: float | None = None):
    now = time.time()
    payload = {
        "pid": os.getpid(),
        "started_at": started_at or now,
        "heartbeat": now,
    }
    tmp_path = lock_path() + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    os.replace(tmp_path, lock_path())


def touch_lock():
    data = read_lock()
    if data.get("pid") != os.getpid():
        return
    try:
        write_lock(data.get("started_at"))
    except Exception:
        pass


def try_lock() -> bool:
    os.makedirs(data_dir(), exist_ok=True)
    with _run_lock:
        for _ in range(2):
            try:
                fd = os.open(lock_path(), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                if not lock_is_stale():
                    return False
                log_event("stale_lock_removed")
                unlock()
                continue
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "pid": os.getpid(),
                        "started_at": time.time(),
                        "heartbeat": time.time(),
                    },
                    f,
                )
            return True
        return False


def unlock():
    try:
        if os.path.exists(lock_path()):
            os.remove(lock_path())
    except Exception:
        pass


def start_browser():
    from playwright.sync_api import sync_playwright

    pw_ctx = sync_playwright().start()
    try:
        return pw_ctx, pw_ctx.chromium.launch(headless=True)
    except Exception:
        pw_ctx.stop()
        raise


def html_extract(url: str, browser=None):
    if USE_PLAYWRIGHT:
        try:
            from playwright.sync_api import sync_playwright

            content = ""
            if browser is not None:
                page = browser.new_page()
                try:
                    page.set_default_timeout(25000)
                    page.goto(url, wait_until="domcontentloaded")
                    content = page.content()
                finally:
                    page.close()
            else:
                with sync_playwright() as p:
                    own_browser = p.chromium.launch(headless=True)
                    try:
                        page = own_browser.new_page()
                        page.set_default_timeout(25000)
                        page.goto(url, wait_until="domcontentloaded")
                        content = page.content()
                    finally:
                        own_browser.close()
            soup = BeautifulSoup(content, "html.parser")
            text = soup.get_text(" ", strip=True)
            if text:
                return text[:8000]
        except Exception:
            log_event("fetch_playwright_failed", url=url)
            pass
    try:
        def fetch():
            sleep_delay()
            return requests.get(
                url,
                timeout=20,
                headers={"User-Agent": get_random_user_agent()},
            )

        r = with_retry(fetch)
        soup = BeautifulSoup(r.text, "html.parser")
        text = soup.get_text(" ", strip=True)
        return text[:8000]
    except Exception:
        log_event("fetch_requests_failed", url=url)
        return ""


FETCH_LIMIT = int(os.environ.get("SOURCE_FETCH_LIMIT") or "100")

def build_tasks(source_names, sites, keywords):
    tasks = []
    for name in source_names:
        source = get_source(name)
        if name == "ddg":
            for site in sites:
                for keyword in keywords:
                    tasks.append(
                        (
                            source,
                            build_query(site, keyword),
                            lambda s=source, a=site, b=keyword: s.search(a, b),
                        )
                    )
        else:
            tasks.append(
                (
                    source,
                    name,
                    lambda s=source: s.fetch(keywords, limit=FETCH_LIMIT),
                )
            )
    return tasks


def wait_while_paused(done: int, total: int, added: int) -> bool:
    while pause_requested() and not stop_requested():
        write_status(
            "paused",
            min(100, int((done / total) * 100)),
            {"running": True, "added": added, "paused": True},
        )
        time.sleep(1)
    return stop_requested()


AI_MAX_PER_RUN = int(os.environ.get("AI_MAX_PER_RUN") or "100")


def ai_input_hash(text: str, cv_text: str, keywords: list[str], fingerprint: str) -> str:
    material = json.dumps([text, cv_text, sorted(keywords), fingerprint], ensure_ascii=False)
    return hashlib.sha1(material.encode("utf-8")).hexdigest()


def default_source_names() -> list[str]:
    from . import watchlist

    names = list(DEFAULT_SOURCES)
    try:
        if watchlist.load():
            names.append("boards")
        if watchlist.load_pages():
            names.append("web")
    except watchlist.WatchlistError:
        pass
    return names


def run_scrape(
    api_key: str,
    lite_mode: bool,
    provider: str | None = "groq",
    api_keys: dict[str, str] | None = None,
    sites: list[str] | None = None,
    keywords: list[str] | None = None,
    cv_text: str | None = None,
    _lock_acquired: bool = False,
    sources: list[str] | None = None,
):
    global _pause_requested, _stop_requested

    if not _lock_acquired and not try_lock():
        log_event("run_rejected", reason="already_running")
        return
    _pause_requested = False
    _stop_requested = False
    try:
        db.init()
        try:
            profile = prof.load()
        except prof.ProfileError as error:
            log_event("profile_unreadable", error=str(error)[:160])
            profile = prof.normalize({})
        use_profile = prof.exists()
        if keywords is None:
            keywords = read_lines(os.path.join(config_dir(), "keywords.txt")) or profile["keywords"]
        if not keywords:
            write_status("no_keywords", 0, {"running": False, "added": 0, "paused": False})
            log_event("run_invalid", reason="no_keywords")
            return

        source_names = [str(n).strip().lower() for n in (sources or profile["sources"] or default_source_names())]
        if sites is None:
            sites = read_lines(os.path.join(config_dir(), "sites.txt")) or profile["sites"]
        sites = [x for x in sites if normalize_site(x)]
        if "ddg" in source_names and not sites:
            sites = default_sites()
            log_event("default_sites_used", count=len(sites))
        if cv_text is None:
            cv_text = read_text(os.path.join(config_dir(), "cv.txt")) or profile["cv_text"]
        try:
            tasks = build_tasks(source_names, sites, keywords)
        except SourceError as error:
            write_status("invalid_sources", 0, {"running": False, "added": 0, "paused": False})
            log_event("run_invalid", reason=str(error))
            return

        run_id = db.start_run()
        fingerprint = prof.fingerprint(profile)
        selected_provider = (provider or "groq").strip().lower()
        keys = {
            "groq": (os.environ.get("GROQ_API_KEY") or "").strip(),
            "anthropic": (os.environ.get("ANTHROPIC_API_KEY") or "").strip(),
            "gemini": (os.environ.get("GEMINI_API_KEY") or "").strip(),
            "openai": (os.environ.get("OPENAI_API_KEY") or "").strip(),
        }
        for k, v in (api_keys or {}).items():
            keys[str(k).strip().lower()] = (v or "").strip()
        if api_key and not keys.get("groq"):
            keys["groq"] = api_key.strip()
        ai = AIService(selected_provider, keys)
        use_ai = ai.enabled and not lite_mode
        log_event(
            "run_started",
            provider=selected_provider,
            use_ai=use_ai,
            lite_mode=bool(lite_mode),
            sources=source_names,
            tasks=len(tasks),
            keywords=len(keywords),
        )
        total = max(1, len(tasks))
        done = 0
        added = 0
        ai_calls = 0
        source_errors = 0
        write_status("starting", 0, {"running": True, "added": 0, "paused": False})

        pw_ctx = None
        shared_browser = None
        needs_pages = use_ai and USE_PLAYWRIGHT and any(not s.has_full_text for s, _, _ in tasks)
        if needs_pages:
            try:
                pw_ctx, shared_browser = start_browser()
            except Exception:
                log_event("browser_launch_failed")

        def status_meta():
            return {
                "running": True,
                "added": added,
                "paused": False,
                "ai_failed": ai.failures,
                "source_errors": source_errors,
            }

        try:
            for source, label, run_task in tasks:
                if wait_while_paused(done, total, added) or stop_requested():
                    log_event("run_stopped")
                    break
                append_log(f"query={label}")
                log_event("query", query=label, source=source.name)
                try:
                    records = run_task()
                except Exception as error:
                    source_errors += 1
                    log_event("source_failed", source=source.name, query=label, error=str(error)[:160])
                    records = []
                if source.name == "ddg":
                    discovery.learn(r.url for r in records)
                for record in records:
                    if stop_requested():
                        break
                    text = record.description
                    if use_ai and not source.has_full_text and record.url:
                        fetched = html_extract(record.url, browser=shared_browser)
                        if fetched:
                            text = fetched
                    scored_text = f"{record.title}. {text}"
                    extra = {}
                    verdict = None
                    if use_profile:
                        result = eligibility.evaluate(eligibility.job_from_record(record, text), profile)
                        verdict = result["verdict"]
                        extra = {
                            "eligibility": result["verdict"],
                            "eligibility_reasons": result["reasons"],
                            "work_mode": result["work_mode"],
                            "seniority": result["seniority"] or None,
                            "sponsorship": result["sponsorship"] or None,
                            "salary_min": result["salary_min"],
                            "salary_max": result["salary_max"],
                            "salary_currency": result["salary_currency"],
                            "profile_fingerprint": fingerprint,
                        }
                    ai_hash = None
                    ask_ai = use_ai and verdict != "not_eligible"
                    if ask_ai:
                        ai_hash = ai_input_hash(scored_text, cv_text, keywords, fingerprint)
                        if db.ai_is_current(db.record_hash(record), ai_hash):
                            db.touch_seen(db.record_hash(record), run_id)
                            continue
                        if ai_calls >= AI_MAX_PER_RUN:
                            if ai_calls == AI_MAX_PER_RUN:
                                log_event("ai_cap_reached", cap=AI_MAX_PER_RUN)
                                ai_calls += 1
                            ask_ai = False
                    if ask_ai:
                        ai_calls += 1
                        score, reasoning = ai.analyze(scored_text, cv_text, keywords, profile if use_profile else None)
                        if is_ai_failure(reasoning):
                            ai_hash = None
                    else:
                        ai_hash = None
                        score, reasoning = ai.lite_score(scored_text, keywords, cv_text)
                    extra["ai_hash"] = ai_hash
                    h = db.upsert_record(record, score, reasoning, run_id, description=text, **extra)
                    if h:
                        added += 1
                done += 1
                write_status("running", min(100, int((done / total) * 100)), status_meta())
        finally:
            if shared_browser:
                try:
                    shared_browser.close()
                except Exception:
                    pass
            if pw_ctx:
                try:
                    pw_ctx.stop()
                except Exception:
                    pass

        final_meta = {**status_meta(), "running": False}
        if stop_requested():
            write_status("stopped", min(100, int((done / total) * 100)), final_meta)
            log_event("run_stopped", added=added)
        else:
            write_status("complete", 100, final_meta)
            log_event("run_complete", added=added, ai_failed=ai.failures, source_errors=source_errors)
            db.finish_run(run_id)
            try:
                from .notifications import check_and_notify

                n = check_and_notify()
                if n > 0:
                    log_event("notifications_sent", count=n)
            except Exception:
                pass
    finally:
        unlock()
