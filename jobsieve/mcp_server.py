from . import db, notifications, tailor, watchlist
from . import profile as prof
from .sources import REGISTRY, SourceError, get_source

LIST_TEXT_CHARS = 400
JOB_TEXT_CHARS = 12000
MAX_LIMIT = 100
INSTRUCTIONS = (
    "Jobsieve keeps job listings in a local SQLite file and checks each one against the user's profile "
    "(eligible, unclear or not eligible, with reasons). Typical flow: get_profile, search_jobs, list_jobs, "
    "get_job for the promising ones, score them yourself with set_score, then set_status as the user decides. "
    "Never describe an unclear job as eligible. Do not invent experience when drafting an application."
)


def brief(job: dict) -> dict:
    return {
        "job_hash": job["job_hash"],
        "title": job.get("title"),
        "company": job.get("company"),
        "location": job.get("location"),
        "remote": job.get("remote"),
        "salary": job.get("salary"),
        "link": job.get("link"),
        "source": job.get("source"),
        "score": job.get("score"),
        "eligibility": job.get("eligibility"),
        "eligibility_reasons": job.get("eligibility_reasons"),
        "status": job.get("status"),
        "freshness": (job.get("freshness") or {}).get("label"),
        "snippet": str(job.get("snippet") or "")[:LIST_TEXT_CHARS],
    }


def resolve(job_hash: str) -> str:
    matches = db.find_hashes(job_hash)
    if len(matches) != 1:
        raise ValueError("no job matches that id" if not matches else "that id matches several jobs; use more characters")
    return matches[0]


def search_jobs(keywords: list[str], sources: list[str] | None = None, limit: int = 30) -> dict:
    """Fetch listings from job sources (feeds, company boards, watched pages), match them to the keywords, save them and check eligibility against the profile."""
    from . import eligibility

    db.init()
    names = sources or ["remoteok", "remotive", "arbeitnow", "himalayas", "jobicy", "workingnomads", "boards"]
    profile = prof.load() if prof.exists() else None
    run_id = db.start_run()
    found, errors = [], {}
    for name in names:
        try:
            records = get_source(name).fetch(keywords, limit=max(1, min(int(limit), MAX_LIMIT)))
        except (SourceError, Exception) as error:
            errors[name] = str(error)[:160]
            continue
        for record in records:
            extra = {}
            if profile:
                result = eligibility.evaluate(eligibility.job_from_record(record, record.description), profile)
                extra = {"eligibility": result["verdict"], "eligibility_reasons": result["reasons"],
                         "work_mode": result["work_mode"], "profile_fingerprint": prof.fingerprint(profile)}
            db.upsert_record(record, None, "", run_id, **extra)
            found.append(db.record_hash(record))
    db.finish_run(run_id)
    saved = {j["job_hash"]: j for j in db.list_jobs(limit=500, include_closed=True, status=list(db.STATUSES))}
    return {"jobs": [brief(saved[h]) for h in dict.fromkeys(found) if h in saved][:limit], "errors": errors}


def list_jobs(status: list[str] | None = None, eligibility: list[str] | None = None, limit: int = 30) -> dict:
    """List saved jobs, best first. Hidden jobs are left out unless status includes 'hidden'."""
    db.init()
    rows = db.list_jobs(limit=max(1, min(int(limit), MAX_LIMIT)), status=status, eligibility=eligibility)
    return {"jobs": [brief(j) for j in rows]}


def get_job(job_hash: str) -> dict:
    """Everything stored about one job, including the full description."""
    db.init()
    job = db.get_job(resolve(job_hash))
    out = brief(job)
    out.update(
        description=str(job.get("description") or "")[:JOB_TEXT_CHARS],
        restrictions=job.get("restrictions"), posted_at=job.get("posted_at"), notes=job.get("notes"),
        reasoning=job.get("reasoning"), freshness=job.get("freshness"), also_seen=job.get("also_seen"),
        tailoring=job.get("tailoring"),
    )
    return out


def set_score(job_hash: str, score: int, reasoning: str) -> dict:
    """Record your own 0-10 score and a short reason for a job. It is kept when later searches refresh the job."""
    db.init()
    full = resolve(job_hash)
    db.set_score(full, score, f"{db.AGENT_PREFIX} {str(reasoning)[:300]}")
    return {"job_hash": full, "score": max(0, min(10, int(score)))}


def set_status(job_hash: str, status: str, notes: str | None = None) -> dict:
    """Move a job to saved, applied, interviewing, offer, rejected, hidden or back to new, with an optional note."""
    db.init()
    return brief(db.set_status(resolve(job_hash), status, notes))


def save_application_draft(job_hash: str, cv_suggestions: list[str], keyword_gaps: list[str], cover_letter: str) -> dict:
    """Save CV suggestions, the requirements the CV does not show, and a cover letter you wrote for a job. Use only facts from the user's CV."""
    db.init()
    full = resolve(job_hash)
    profile = prof.load()
    job = db.get_job(full)
    content = {"cv_suggestions": [str(x) for x in cv_suggestions][:8], "keyword_gaps": [str(x) for x in keyword_gaps][:20],
               "cover_letter": str(cover_letter).strip(), "provider": "agent", "model": ""}
    content["unverified_numbers"] = tailor.unverified_numbers(content, profile["cv_text"], job.get("description") or "")
    db.save_tailoring(full, content)
    return {"job_hash": full, "unverified_numbers": content["unverified_numbers"]}


def get_profile() -> dict:
    """The user's saved profile: where they live and may work, work modes, salary floor, keywords and CV text."""
    return {"exists": prof.exists(), "profile": prof.load()}


def watch_company(board: str, company: str) -> dict:
    """Add a company to the watchlist so searches read its career board. Boards: greenhouse, lever, ashby, smartrecruiters."""
    return {"added": watchlist.add(board, company, added_by="agent")}


def digest() -> dict:
    """Matches added since the last digest was sent (does not send or reset anything)."""
    db.init()
    matches = notifications.pending_matches()
    return {"count": len(matches), "markdown": notifications.render_markdown(matches, 30) if matches else ""}


def list_sources() -> dict:
    """The sources search_jobs can read, with their display names."""
    return {"sources": {name: source.label for name, source in REGISTRY.items()}}


TOOLS = (search_jobs, list_jobs, get_job, set_score, set_status, save_application_draft, get_profile, watch_company, digest, list_sources)


def build_server():
    try:
        from mcp.server.mcpserver import MCPServer as Server
    except ImportError:
        try:
            from mcp.server.fastmcp import FastMCP as Server
        except ImportError as error:
            raise SystemExit("the MCP server needs its extra: pip install 'jobsieve[mcp]'") from error
    server = Server("jobsieve", instructions=INSTRUCTIONS)
    for function in TOOLS:
        server.tool()(function)
    return server


def main() -> None:
    build_server().run()
