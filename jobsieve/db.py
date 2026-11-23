import os
import sqlite3
import hashlib
import json
import uuid
from datetime import datetime, timezone

from .util import normalize_url


def data_dir() -> str:
    return os.environ.get("DATA_DIR", "./data")


def db_path() -> str:
    return os.path.join(data_dir(), "jobs.sqlite")


def connect():
    os.makedirs(data_dir(), exist_ok=True)
    conn = sqlite3.connect(db_path(), check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


MAX_LIST_LIMIT = 1000


def table_columns(cur, table: str) -> set[str]:
    cur.execute(f"PRAGMA table_info({table})")
    return {row["name"] for row in cur.fetchall()}


def migrate_to_v1(cur):
    existing = table_columns(cur, "jobs")
    for column in ("run_id", "last_seen", "updated_at"):
        if column not in existing:
            cur.execute(f"ALTER TABLE jobs ADD COLUMN {column} TEXT")
    cur.execute("UPDATE jobs SET last_seen = created_at WHERE last_seen IS NULL")
    cur.execute(
        "CREATE TABLE IF NOT EXISTS runs ("
        "run_id TEXT PRIMARY KEY, started_at TEXT, finished_at TEXT)"
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_jobs_run_id ON jobs(run_id)")


def rekey_jobs_by_url(cur):
    rows = cur.execute(
        "SELECT id, title, site, link FROM jobs ORDER BY last_seen DESC, id DESC"
    ).fetchall()
    taken = set()
    for row in rows:
        new_hash = job_hash(row["title"] or "", row["site"] or "", row["link"] or "")
        if new_hash in taken:
            cur.execute("DELETE FROM jobs WHERE id = ?", (row["id"],))
            continue
        taken.add(new_hash)
        cur.execute("UPDATE jobs SET job_hash = ? WHERE id = ?", (new_hash, row["id"]))


def migrate_to_v2(cur):
    existing = table_columns(cur, "jobs")
    for column in ("source", "location", "salary", "posted_at", "description"):
        if column not in existing:
            cur.execute(f"ALTER TABLE jobs ADD COLUMN {column} TEXT")
    if "remote" not in existing:
        cur.execute("ALTER TABLE jobs ADD COLUMN remote INTEGER")
    cur.execute("UPDATE jobs SET source = 'ddg' WHERE source IS NULL")
    rekey_jobs_by_url(cur)


def migrate_to_v3(cur):
    existing = table_columns(cur, "jobs")
    for column in (
        "restrictions", "eligibility", "eligibility_reasons", "work_mode",
        "seniority", "sponsorship", "salary_currency", "profile_fingerprint",
    ):
        if column not in existing:
            cur.execute(f"ALTER TABLE jobs ADD COLUMN {column} TEXT")
    for column in ("salary_min", "salary_max"):
        if column not in existing:
            cur.execute(f"ALTER TABLE jobs ADD COLUMN {column} REAL")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_jobs_eligibility ON jobs(eligibility)")


MIGRATIONS = [migrate_to_v1, migrate_to_v2, migrate_to_v3]


def init():
    conn = connect()
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE IF NOT EXISTS jobs ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "job_hash TEXT UNIQUE, "
        "title TEXT, company TEXT, link TEXT, site TEXT, "
        "snippet TEXT, score INTEGER, reasoning TEXT, created_at TEXT"
        ")"
    )
    version = cur.execute("PRAGMA user_version").fetchone()[0]
    for target, migration in enumerate(MIGRATIONS, start=1):
        if version < target:
            migration(cur)
            cur.execute(f"PRAGMA user_version = {target}")
    conn.commit()
    cur.close()
    conn.close()


AI_FAILED_PREFIX = "ai_failed:"
LITE_PREFIX = "matched_keywords="


def is_ai_scored(reasoning) -> bool:
    text = str(reasoning or "")
    return bool(text) and not text.startswith((AI_FAILED_PREFIX, LITE_PREFIX))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def job_hash(title: str, site: str, link: str) -> str:
    identity = normalize_url(link) if link else f"{title}|{site}"
    return hashlib.md5(identity.encode("utf-8")).hexdigest()


def start_run() -> str:
    run_id = uuid.uuid4().hex
    conn = connect()
    conn.execute(
        "INSERT INTO runs (run_id, started_at) VALUES (?, ?)", (run_id, now_iso())
    )
    conn.commit()
    conn.close()
    return run_id


def finish_run(run_id: str):
    conn = connect()
    conn.execute(
        "UPDATE runs SET finished_at = ? WHERE run_id = ?", (now_iso(), run_id)
    )
    conn.commit()
    conn.close()


def latest_run_id() -> str | None:
    conn = connect()
    row = conn.execute(
        "SELECT run_id FROM runs ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return row["run_id"] if row else None


DETAIL_FIELDS = (
    "source", "location", "remote", "salary", "posted_at", "description",
    "restrictions", "eligibility", "eligibility_reasons", "work_mode", "seniority",
    "sponsorship", "salary_min", "salary_max", "salary_currency", "profile_fingerprint",
)


def prepare_details(details: dict) -> dict:
    unknown = set(details) - set(DETAIL_FIELDS)
    if unknown:
        raise TypeError(f"unknown job field(s): {', '.join(sorted(unknown))}")
    values = {field: details.get(field) for field in DETAIL_FIELDS}
    if values["remote"] is not None:
        values["remote"] = int(bool(values["remote"]))
    if isinstance(values["eligibility_reasons"], (list, tuple)):
        values["eligibility_reasons"] = json.dumps(list(values["eligibility_reasons"]), ensure_ascii=False)
    return values


def upsert_job(title, company, link, site, snippet, score, reasoning, run_id=None, **details):
    h = job_hash(title or "", site or "", link or "")
    now = now_iso()
    values = prepare_details(details)
    conn = connect()
    cur = conn.cursor()
    columns = ", ".join(DETAIL_FIELDS)
    marks = ", ".join("?" for _ in DETAIL_FIELDS)
    cur.execute(
        "INSERT OR IGNORE INTO jobs "
        "(job_hash, title, company, link, site, snippet, score, reasoning, "
        f"created_at, run_id, last_seen, updated_at, {columns}) "
        f"VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, {marks})",
        (
            h, title, company, link, site, snippet, score, reasoning,
            now, run_id, now, now,
            *(values[f] for f in DETAIL_FIELDS),
        ),
    )
    inserted = bool(cur.rowcount)
    if not inserted:
        existing = cur.execute(
            "SELECT reasoning FROM jobs WHERE job_hash = ?", (h,)
        ).fetchone()
        keep_previous_score = (
            existing is not None
            and is_ai_scored(existing["reasoning"])
            and str(reasoning or "").startswith(AI_FAILED_PREFIX)
        )
        detail_sql = ", ".join(f"{f} = COALESCE(?, {f})" for f in DETAIL_FIELDS)
        detail_values = [values[f] for f in DETAIL_FIELDS]
        if keep_previous_score:
            cur.execute(
                f"UPDATE jobs SET run_id = ?, last_seen = ?, {detail_sql} "
                "WHERE job_hash = ?",
                (run_id, now, *detail_values, h),
            )
        else:
            cur.execute(
                "UPDATE jobs SET snippet = ?, score = ?, reasoning = ?, "
                f"run_id = ?, last_seen = ?, updated_at = ?, {detail_sql} "
                "WHERE job_hash = ?",
                (snippet, score, reasoning, run_id, now, now, *detail_values, h),
            )
    conn.commit()
    cur.close()
    conn.close()
    return h if inserted else ""


SNIPPET_CHARS = 500


def upsert_record(record, score, reasoning, run_id=None, description=None, **extra):
    return upsert_job(
        title=record.title,
        company=record.company,
        link=record.url,
        site=record.company if record.source == "ddg" else record.source,
        snippet=record.description[:SNIPPET_CHARS],
        score=score,
        reasoning=reasoning,
        run_id=run_id,
        source=record.source,
        location=record.location or None,
        remote=record.remote,
        salary=record.salary or None,
        posted_at=record.posted_at or None,
        description=(description if description is not None else record.description) or None,
        restrictions=record.restrictions or None,
        **extra,
    )


def record_hash(record) -> str:
    site = record.company if record.source == "ddg" else record.source
    return job_hash(record.title, site, record.url)


def set_score(job_hash_value: str, score: int, reasoning: str) -> bool:
    conn = connect()
    cur = conn.execute(
        "UPDATE jobs SET score = ?, reasoning = ?, updated_at = ? WHERE job_hash = ?",
        (max(0, min(10, int(score))), reasoning, now_iso(), job_hash_value),
    )
    conn.commit()
    changed = bool(cur.rowcount)
    conn.close()
    return changed


def decode_job(row) -> dict:
    job = dict(row)
    reasons = job.get("eligibility_reasons")
    if reasons:
        try:
            job["eligibility_reasons"] = json.loads(reasons)
        except ValueError:
            job["eligibility_reasons"] = [reasons]
    return job


def list_jobs(limit=200, run_id=None, eligibility=None):
    limit = max(1, min(int(limit), MAX_LIST_LIMIT))
    where, params = [], []
    if run_id:
        where.append("(run_id = ? OR source LIKE 'capture:%')")
        params.append(run_id)
    if eligibility:
        wanted = [e for e in eligibility if e in ("eligible", "not_eligible", "unknown", "unchecked")]
        marks = ", ".join("?" for e in wanted if e != "unchecked")
        clauses = []
        if marks:
            clauses.append(f"eligibility IN ({marks})")
            params.extend(e for e in wanted if e != "unchecked")
        if "unchecked" in wanted:
            clauses.append("eligibility IS NULL")
        where.append("(" + " OR ".join(clauses or ["0"]) + ")")
    sql = "SELECT * FROM jobs"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY score DESC, created_at DESC LIMIT ?"
    conn = connect()
    cur = conn.cursor()
    cur.execute(sql, (*params, limit))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [decode_job(r) for r in rows]


def jobs_for_evaluation():
    conn = connect()
    rows = conn.execute(
        "SELECT job_hash, title, company, location, restrictions, remote, description, "
        "salary, profile_fingerprint FROM jobs"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def save_evaluation(job_hash_value: str, evaluation: dict, fingerprint: str):
    values = prepare_details(
        {
            "eligibility": evaluation["verdict"],
            "eligibility_reasons": evaluation["reasons"],
            "work_mode": evaluation["work_mode"],
            "seniority": evaluation["seniority"] or None,
            "sponsorship": evaluation["sponsorship"] or None,
            "salary_min": evaluation["salary_min"],
            "salary_max": evaluation["salary_max"],
            "salary_currency": evaluation["salary_currency"],
            "profile_fingerprint": fingerprint,
        }
    )
    changes = {k: v for k, v in values.items() if k in (
        "eligibility", "eligibility_reasons", "work_mode", "seniority", "sponsorship",
        "salary_min", "salary_max", "salary_currency", "profile_fingerprint",
    )}
    sets = ", ".join(f"{k} = ?" for k in changes)
    conn = connect()
    conn.execute(f"UPDATE jobs SET {sets} WHERE job_hash = ?", (*changes.values(), job_hash_value))
    conn.commit()
    conn.close()


def count_jobs() -> int:
    conn = connect()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS n FROM jobs")
    n = cur.fetchone()["n"]
    cur.close()
    conn.close()
    return int(n)


def get_jobs_since(timestamp: str):
    conn = connect()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM jobs WHERE created_at > ? ORDER BY score DESC",
        (timestamp,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [dict(r) for r in rows]
