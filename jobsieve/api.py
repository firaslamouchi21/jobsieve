import csv
import hmac
import io
import json
import os
import threading
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator

from . import db, eligibility, places, scraper
from .ai_service import AIService
from .sources.base import JobRecord, html_to_text
from . import profile as prof


@asynccontextmanager
async def lifespan(_app):
    scraper.recover_from_crash()
    yield


def require_token(request: Request):
    token = (os.environ.get("API_TOKEN") or "").strip()
    if not token or request.url.path == "/health":
        return
    header = request.headers.get("authorization", "")
    supplied = header[7:].strip() if header.lower().startswith("bearer ") else ""
    if not hmac.compare_digest(supplied.encode("utf-8"), token.encode("utf-8")):
        raise HTTPException(
            status_code=401,
            detail="invalid or missing API token",
            headers={"WWW-Authenticate": "Bearer"},
        )


api = FastAPI(lifespan=lifespan, dependencies=[Depends(require_token)])


class RunRequest(BaseModel):
    provider: str | None = "groq"
    api_key: str | None = ""
    groq_api_key: str | None = ""
    anthropic_api_key: str | None = ""
    gemini_api_key: str | None = ""
    lite_mode: bool = False
    sites: list[str] | None = None
    keywords: list[str] | None = None
    cv_text: str | None = None
    sources: list[str] | None = None


@api.get("/health")
def health():
    return {"ok": True}


@api.get("/config")
def config():
    return {
        "providers": {
            name: bool((os.environ.get(f"{name.upper()}_API_KEY") or "").strip())
            for name in ("groq", "anthropic", "gemini")
        },
        "auth_required": bool((os.environ.get("API_TOKEN") or "").strip()),
    }


@api.get("/status")
def status():
    try:
        with open(scraper.status_path(), "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception:
        payload = None
    if isinstance(payload, dict):
        if payload.get("running") and not scraper.is_running():
            payload.update({"running": False, "paused": False, "message": "interrupted"})
        return payload
    return {
        "message": "idle",
        "progress": 0,
        "running": scraper.is_running(),
        "added": 0,
        "paused": False,
    }


def jobs_for(limit: int, run: str | None, eligibility_filter: str | None = None):
    db.init()
    wanted = [x.strip() for x in (eligibility_filter or "").split(",") if x.strip()] or None
    run_id = None
    if run == "latest":
        run_id = db.latest_run_id()
        if not run_id:
            return []
    return db.list_jobs(limit=limit, run_id=run_id, eligibility=wanted)


@api.get("/jobs")
def jobs(limit: int = 200, run: str | None = None, eligibility: str | None = None):
    return {"jobs": jobs_for(limit, run, eligibility)}


@api.get("/export/json")
def export_json(limit: int = 200, run: str | None = None, eligibility: str | None = None):
    return jobs_for(limit, run, eligibility)


@api.get("/export/csv")
def export_csv(limit: int = 200, run: str | None = None, eligibility: str | None = None):
    rows = [
        {**r, "eligibility_reasons": "; ".join(r["eligibility_reasons"])}
        if isinstance(r.get("eligibility_reasons"), list)
        else r
        for r in jobs_for(limit, run, eligibility)
    ]
    fieldnames = []
    for r in rows:
        for k in r.keys():
            if k not in fieldnames:
                fieldnames.append(k)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fieldnames)
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return Response(content=buf.getvalue(), media_type="text/csv")


@api.get("/profile")
def get_profile():
    try:
        return {"exists": prof.exists(), "profile": prof.load()}
    except prof.ProfileError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error


@api.put("/profile")
def put_profile(body: dict):
    try:
        saved = prof.save(body)
    except prof.ProfileError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    db.init()
    return {"profile": saved, "reevaluated": eligibility.reevaluate_stored(saved)}


class IngestRequest(BaseModel):
    url: str = Field(max_length=2048)
    title: str = Field(min_length=1, max_length=300)
    company: str = Field(default="", max_length=200)
    location: str = Field(default="", max_length=300)
    description: str = Field(default="", max_length=60000)
    salary: str = Field(default="", max_length=200)
    posted_at: str = Field(default="", max_length=40)
    restrictions: str = Field(default="", max_length=300)
    remote: bool | None = None
    site: str = Field(default="", max_length=60)

    @field_validator("url")
    @classmethod
    def only_web_urls(cls, value: str) -> str:
        parts = urlsplit(value.strip())
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise ValueError("url must be an http(s) address")
        return value.strip()


def capture_label(site: str, url: str) -> str:
    host = (site or urlsplit(url).netloc).lower().removeprefix("www.")
    safe = "".join(c for c in host if c.isalnum() or c in ".-")[:40]
    return f"capture:{safe or 'web'}"


@api.post("/ingest")
def ingest(body: IngestRequest):
    db.init()
    try:
        profile = prof.load()
    except prof.ProfileError:
        profile = prof.normalize({})
    location = body.location.strip()
    if not location:
        location = ", ".join(places.place_phrases(html_to_text(body.description)[:400]))
    record = JobRecord(
        title=body.title.strip(),
        company=body.company.strip(),
        url=body.url,
        source=capture_label(body.site, body.url),
        location=location,
        remote=body.remote,
        salary=body.salary.strip(),
        posted_at=body.posted_at.strip(),
        description=html_to_text(body.description),
        restrictions=body.restrictions.strip(),
    )
    score, reasoning = AIService("lite", {}).lite_score(
        f"{record.title}. {record.description}", profile["keywords"], profile["cv_text"]
    )
    extra = {}
    verdict = None
    if prof.exists():
        verdict = eligibility.evaluate(eligibility.job_from_record(record), profile)
        extra = {
            "eligibility": verdict["verdict"],
            "eligibility_reasons": verdict["reasons"],
            "work_mode": verdict["work_mode"],
            "seniority": verdict["seniority"] or None,
            "sponsorship": verdict["sponsorship"] or None,
            "salary_min": verdict["salary_min"],
            "salary_max": verdict["salary_max"],
            "salary_currency": verdict["salary_currency"],
            "profile_fingerprint": prof.fingerprint(profile),
        }
    created = db.upsert_record(record, score, reasoning, None, **extra)
    return {
        "job_hash": db.record_hash(record),
        "is_new": bool(created),
        "score": score,
        "eligibility": verdict["verdict"] if verdict else None,
        "reasons": verdict["reasons"] if verdict else [],
    }


@api.post("/run")
def run(req: RunRequest):
    if not scraper.try_lock():
        return {"started": False, "running": True}
    keys = {
        "groq": (req.groq_api_key or "").strip(),
        "anthropic": (req.anthropic_api_key or "").strip(),
        "gemini": (req.gemini_api_key or "").strip(),
    }
    t = threading.Thread(
        target=scraper.run_scrape,
        args=(
            req.api_key or "",
            bool(req.lite_mode),
            req.provider or "groq",
            keys,
            req.sites,
            req.keywords,
            req.cv_text,
        ),
        kwargs={"_lock_acquired": True, "sources": req.sources},
        daemon=True,
    )
    t.start()
    return {"started": True}


@api.post("/pause")
def pause():
    if not scraper.is_running():
        return {"paused": False, "running": False}
    scraper.request_pause()
    return {"paused": True, "running": True}


@api.post("/resume")
def resume():
    if not scraper.is_running():
        return {"paused": False, "running": False}
    scraper.request_resume()
    return {"paused": False, "running": True}


@api.post("/stop")
def stop():
    if not scraper.is_running():
        return {"stopping": False, "running": False}
    scraper.request_stop()
    scraper.request_resume()
    return {"stopping": True, "running": True}
