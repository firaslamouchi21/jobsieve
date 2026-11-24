import os
import sqlite3
import hashlib
import json
import uuid
from datetime import datetime, timezone

from . import duplicates, freshness
from .util import log_event, normalize_url


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


def migrate_to_v4(cur):
    existing = table_columns(cur, "jobs")
    for column in ("duplicate_of", "also_seen"):
        if column not in existing:
            cur.execute(f"ALTER TABLE jobs ADD COLUMN {column} TEXT")


def migrate_to_v5(cur):
    existing = table_columns(cur, "jobs")
    for column in ("expires_at", "closed_at"):
        if column not in existing:
            cur.execute(f"ALTER TABLE jobs ADD COLUMN {column} TEXT")
    if "repost_count" not in existing:
        cur.execute("ALTER TABLE jobs ADD COLUMN repost_count INTEGER DEFAULT 0")


def migrate_to_v6(cur):
    existing = table_columns(cur, "jobs")
    if "status" not in existing:
        cur.execute("ALTER TABLE jobs ADD COLUMN status TEXT DEFAULT 'new'")
    for column in ("notes", "status_at"):
        if column not in existing:
            cur.execute(f"ALTER TABLE jobs ADD COLUMN {column} TEXT")
    cur.execute("UPDATE jobs SET status = 'new' WHERE status IS NULL")
    cur.execute(
        "CREATE TABLE IF NOT EXISTS events ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, job_hash TEXT, kind TEXT, detail TEXT, at TEXT)"
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_events_kind_at ON events(kind, at)")


def migrate_to_v7(cur):
    cur.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")


def migrate_to_v8(cur):
    existing = table_columns(cur, "jobs")
    for column in ("ai_hash", "tailoring"):
        if column not in existing:
            cur.execute(f"ALTER TABLE jobs ADD COLUMN {column} TEXT")


MIGRATIONS = [
    migrate_to_v1, migrate_to_v2, migrate_to_v3, migrate_to_v4, migrate_to_v5, migrate_to_v6, migrate_to_v7,
    migrate_to_v8,
]


def get_meta(key: str, default: str = "") -> str:
    conn = connect()
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    except sqlite3.OperationalError:
        return default
    finally:
        conn.close()
    return row["value"] if row else default


def set_meta(key: str, value: str) -> None:
    init()
    conn = connect()
    conn.execute("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))
    conn.commit()
    conn.close()

STATUSES = ("new", "saved", "applied", "interviewing", "offer", "rejected", "hidden")
MAX_NOTE_CHARS = 2000


class JobNotFound(LookupError):
    pass


def set_status(job_hash_value: str, status=None, notes=None) -> dict:
    if status is not None and status not in STATUSES:
        raise ValueError(f"status must be one of: {', '.join(STATUSES)}")
    if notes is not None and len(str(notes)) > MAX_NOTE_CHARS:
        raise ValueError(f"notes are limited to {MAX_NOTE_CHARS} characters")
    conn = connect()
    row = conn.execute("SELECT status FROM jobs WHERE job_hash = ?", (job_hash_value,)).fetchone()
    if row is None:
        conn.close()
        raise JobNotFound(job_hash_value)
    now = now_iso()
    if status is not None and status != (row["status"] or "new"):
        conn.execute("UPDATE jobs SET status = ?, status_at = ? WHERE job_hash = ?", (status, now, job_hash_value))
        conn.execute(
            "INSERT INTO events (job_hash, kind, detail, at) VALUES (?, 'status', ?, ?)",
            (job_hash_value, status, now),
        )
    if notes is not None:
        conn.execute("UPDATE jobs SET notes = ? WHERE job_hash = ?", (str(notes), job_hash_value))
    conn.commit()
    job = decode_job(conn.execute("SELECT * FROM jobs WHERE job_hash = ?", (job_hash_value,)).fetchone())
    conn.close()
    return job


def count_new_since(timestamp: str) -> int:
    conn = connect()
    n = conn.execute(
        "SELECT COUNT(*) AS n FROM jobs WHERE created_at > ? AND eligibility = 'eligible' "
        "AND COALESCE(status, 'new') = 'new' AND duplicate_of IS NULL AND closed_at IS NULL",
        (timestamp,),
    ).fetchone()["n"]
    conn.close()
    return int(n)


def ai_is_current(job_hash_value: str, ai_hash: str) -> bool:
    conn = connect()
    row = conn.execute("SELECT reasoning, ai_hash FROM jobs WHERE job_hash = ?", (job_hash_value,)).fetchone()
    conn.close()
    return bool(row and row["ai_hash"] == ai_hash and is_ai_scored(row["reasoning"]))


def touch_seen(job_hash_value: str, run_id) -> None:
    conn = connect()
    conn.execute("UPDATE jobs SET run_id = ?, last_seen = ?, closed_at = NULL WHERE job_hash = ?", (run_id, now_iso(), job_hash_value))
    conn.commit()
    conn.close()


def save_tailoring(job_hash_value: str, content: dict) -> None:
    conn = connect()
    conn.execute("UPDATE jobs SET tailoring = ? WHERE job_hash = ?", (json.dumps(content, ensure_ascii=False), job_hash_value))
    conn.commit()
    conn.close()


def get_job(job_hash_value: str):
    conn = connect()
    row = conn.execute("SELECT * FROM jobs WHERE job_hash = ?", (job_hash_value,)).fetchone()
    conn.close()
    return decode_job(row) if row else None


def summary(last_visit: str) -> dict:
    conn = connect()
    visible = "duplicate_of IS NULL AND closed_at IS NULL AND (expires_at IS NULL OR expires_at > ?)"
    now = now_iso()
    by_status = conn.execute(
        f"SELECT COALESCE(status, 'new') AS k, COUNT(*) AS n FROM jobs WHERE {visible} GROUP BY k", (now,)
    ).fetchall()
    verdicts = conn.execute(
        "SELECT COALESCE(eligibility, 'unchecked') AS k, COUNT(*) AS n FROM jobs "
        f"WHERE {visible} AND COALESCE(status, 'new') = 'new' GROUP BY k", (now,)
    ).fetchall()
    conn.close()
    return {
        "by_status": {r["k"]: r["n"] for r in by_status},
        "inbox_by_eligibility": {r["k"]: r["n"] for r in verdicts},
        "new_since_visit": count_new_since(last_visit) if last_visit else 0,
    }


def find_hashes(prefix: str) -> list[str]:
    prefix = "".join(c for c in str(prefix) if c.isalnum())
    if len(prefix) < 6:
        return []
    conn = connect()
    rows = conn.execute("SELECT job_hash FROM jobs WHERE job_hash LIKE ? LIMIT 2", (prefix + "%",)).fetchall()
    conn.close()
    return [r["job_hash"] for r in rows]


def event_counts(since: str) -> dict:
    conn = connect()
    rows = conn.execute(
        "SELECT detail, COUNT(*) AS n FROM events WHERE kind = 'status' AND at >= ? GROUP BY detail", (since,)
    ).fetchall()
    conn.close()
    return {r["detail"]: r["n"] for r in rows}


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


AGENT_PREFIX = "agent:"


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
    try:
        mark_duplicates()
    except sqlite3.Error as error:
        log_event("duplicate_check_failed", error=str(error)[:120])


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
    "expires_at", "ai_hash",
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


def republished(old, new) -> bool:
    try:
        before = datetime.fromisoformat(str(old).replace("Z", "+00:00"))
        after = datetime.fromisoformat(str(new).replace("Z", "+00:00"))
    except ValueError:
        return False
    if before.tzinfo is None:
        before = before.replace(tzinfo=timezone.utc)
    if after.tzinfo is None:
        after = after.replace(tzinfo=timezone.utc)
    return (after - before).total_seconds() > 86400


def mark_closed(links) -> int:
    links = [l for l in links if l]
    if not links:
        return 0
    conn = connect()
    count = 0
    for start in range(0, len(links), 500):
        chunk = links[start:start + 500]
        cur = conn.execute(
            f"UPDATE jobs SET closed_at = ? WHERE closed_at IS NULL AND link IN ({', '.join('?' for _ in chunk)})",
            (now_iso(), *chunk),
        )
        count += cur.rowcount
    conn.commit()
    conn.close()
    return count


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
            "SELECT reasoning, posted_at FROM jobs WHERE job_hash = ?", (h,)
        ).fetchone()
        if existing is not None and republished(existing["posted_at"], values["posted_at"]):
            cur.execute("UPDATE jobs SET repost_count = COALESCE(repost_count, 0) + 1 WHERE job_hash = ?", (h,))
        cur.execute("UPDATE jobs SET closed_at = NULL WHERE job_hash = ?", (h,))
        keep_previous_score = existing is not None and (
            (is_ai_scored(existing["reasoning"]) and str(reasoning or "").startswith(AI_FAILED_PREFIX))
            or (str(existing["reasoning"] or "").startswith(AGENT_PREFIX) and not str(reasoning or "").startswith(AGENT_PREFIX))
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
        expires_at=record.expires_at or None,
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
    try:
        job["also_seen"] = json.loads(job.get("also_seen") or "[]")
    except ValueError:
        job["also_seen"] = []
    job["freshness"] = freshness.assess(job)
    try:
        job["tailoring"] = json.loads(job["tailoring"]) if job.get("tailoring") else None
    except ValueError:
        job["tailoring"] = None
    reasons = job.get("eligibility_reasons")
    if reasons:
        try:
            job["eligibility_reasons"] = json.loads(reasons)
        except ValueError:
            job["eligibility_reasons"] = [reasons]
    return job


def mark_duplicates():
    conn = connect()
    rows = conn.execute(
        "SELECT job_hash, company, title, location, source, link, description, updated_at FROM jobs"
    ).fetchall()
    groups: dict[str, list] = {}
    for row in rows:
        key = duplicates.duplicate_key(row["company"], row["title"], row["location"], row["source"])
        if key:
            groups.setdefault(key, []).append(row)
    marks = {row["job_hash"]: (None, None) for row in rows}
    for group in groups.values():
        if len(group) < 2:
            continue
        ranked = sorted(group, key=lambda r: duplicates.preference(r["source"], r["description"], r["updated_at"]))
        best, rest = ranked[0], ranked[1:]
        marks[best["job_hash"]] = (None, json.dumps([{"source": r["source"], "url": r["link"]} for r in rest]))
        for r in rest:
            marks[r["job_hash"]] = (best["job_hash"], None)
    conn.executemany(
        "UPDATE jobs SET duplicate_of = ?, also_seen = ? WHERE job_hash = ?",
        [(dup, seen, h) for h, (dup, seen) in marks.items()],
    )
    conn.commit()
    conn.close()


def spreadsheet_safe(value):
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def csv_row(job: dict) -> dict:
    row = dict(job)
    if isinstance(row.get("eligibility_reasons"), list):
        row["eligibility_reasons"] = "; ".join(row["eligibility_reasons"])
    state = row.pop("freshness", None)
    if isinstance(state, dict):
        row["freshness"] = state["label"]
        row["freshness_facts"] = "; ".join(state["facts"])
    if isinstance(row.get("also_seen"), list):
        row["also_seen"] = "; ".join(f"{o.get('source')} {o.get('url')}" for o in row["also_seen"])
    return {key: spreadsheet_safe(value) for key, value in row.items()}


def list_jobs(limit=200, run_id=None, eligibility=None, include_duplicates=False, include_closed=False, status=None):
    limit = max(1, min(int(limit), MAX_LIST_LIMIT))
    where, params = [], []
    if not include_duplicates:
        where.append("duplicate_of IS NULL")
    if status:
        wanted_status = [x for x in status if x in STATUSES]
        where.append(f"COALESCE(status, 'new') IN ({', '.join('?' for _ in wanted_status) or 'NULL'})")
        params.extend(wanted_status)
    else:
        where.append("COALESCE(status, 'new') != 'hidden'")
    if not include_closed:
        where.append("closed_at IS NULL AND (expires_at IS NULL OR expires_at > ?)")
        params.append(now_iso())
    if run_id:
        where.append(
            "(run_id = ? OR source LIKE 'capture:%' OR job_hash IN "
            "(SELECT duplicate_of FROM jobs WHERE run_id = ? AND duplicate_of IS NOT NULL))"
        )
        params.extend([run_id, run_id])
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
    sql += (
        " ORDER BY CASE eligibility WHEN 'eligible' THEN 0 WHEN 'unknown' THEN 1 WHEN 'not_eligible' THEN 3 ELSE 2 END,"
        " score DESC, COALESCE(posted_at, created_at) DESC LIMIT ?"
    )
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


EVALUATION_FIELDS = (
    "eligibility", "eligibility_reasons", "work_mode", "seniority", "sponsorship",
    "salary_min", "salary_max", "salary_currency", "profile_fingerprint",
)


def save_evaluations(evaluations, fingerprint: str):
    rows = []
    for job_hash_value, evaluation in evaluations:
        values = prepare_details({
            "eligibility": evaluation["verdict"],
            "eligibility_reasons": evaluation["reasons"],
            "work_mode": evaluation["work_mode"],
            "seniority": evaluation["seniority"] or None,
            "sponsorship": evaluation["sponsorship"] or None,
            "salary_min": evaluation["salary_min"],
            "salary_max": evaluation["salary_max"],
            "salary_currency": evaluation["salary_currency"],
            "profile_fingerprint": fingerprint,
        })
        rows.append((*(values[f] for f in EVALUATION_FIELDS), job_hash_value))
    conn = connect()
    sets = ", ".join(f"{field} = ?" for field in EVALUATION_FIELDS)
    conn.executemany(f"UPDATE jobs SET {sets} WHERE job_hash = ?", rows)
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
        "SELECT * FROM jobs WHERE created_at > ? AND COALESCE(status, 'new') IN ('new', 'saved') "
        "AND duplicate_of IS NULL AND closed_at IS NULL AND COALESCE(eligibility, '') != 'not_eligible' "
        "ORDER BY score DESC",
        (timestamp,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [dict(r) for r in rows]
