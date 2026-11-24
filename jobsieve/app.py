import os
import time
from datetime import datetime, timezone
import requests
import streamlit as st
from jobsieve import db
from jobsieve.sources import REGISTRY, available_sources

DATA_DIR = os.environ.get("DATA_DIR", "./data")
SCRAPER_URL = os.environ.get("SCRAPER_URL", "http://localhost:8000")
API_TOKEN = os.environ.get("API_TOKEN", "").strip()


def auth_headers():
    return {"Authorization": f"Bearer {API_TOKEN}"} if API_TOKEN else {}


def fetch_config():
    try:
        r = requests.get(f"{SCRAPER_URL}/config", headers=auth_headers(), timeout=3)
        r.raise_for_status()
        return r.json().get("providers", {})
    except Exception:
        return {}


def fetch_status():
    try:
        r = requests.get(f"{SCRAPER_URL}/status", headers=auth_headers(), timeout=3)
        return r.json()
    except Exception:
        return {"message": "offline", "progress": 0, "running": False, "added": 0, "paused": False}


def parse_lines(raw: str):
    return [x.strip() for x in str(raw or "").splitlines() if x.strip()]


def trigger(
    provider: str,
    groq_api_key: str,
    anthropic_api_key: str,
    gemini_api_key: str,
    lite_mode: bool,
    sites: list[str],
    keywords: list[str],
    cv_text: str,
    sources: list[str] | None = None,
):
    payload = {
        "provider": provider,
        "api_key": groq_api_key or "",
        "groq_api_key": groq_api_key or "",
        "anthropic_api_key": anthropic_api_key or "",
        "gemini_api_key": gemini_api_key or "",
        "lite_mode": bool(lite_mode),
        "sites": sites,
        "keywords": keywords,
        "cv_text": cv_text,
        "sources": sources or ["ddg"],
    }
    try:
        r = requests.post(f"{SCRAPER_URL}/run", json=payload, headers=auth_headers(), timeout=5)
        r.raise_for_status()
        return True, ""
    except Exception as e:
        return False, str(e)


def control(action: str):
    try:
        r = requests.post(f"{SCRAPER_URL}/{action}", headers=auth_headers(), timeout=5)
        r.raise_for_status()
        return True, ""
    except Exception as e:
        return False, str(e)


def profile_request(method: str, payload: dict | None = None):
    try:
        r = requests.request(
            method, f"{SCRAPER_URL}/profile", json=payload, headers=auth_headers(), timeout=10
        )
    except Exception as e:
        return None, f"cannot reach the API: {e}"
    if r.status_code >= 400:
        try:
            return None, str(r.json().get("detail") or r.text)
        except Exception:
            return None, r.text
    return r.json(), ""


VERDICT_LABELS = {
    "eligible": ":green[Eligible]",
    "unknown": ":orange[Unclear]",
    "not_eligible": ":red[Not eligible]",
}
FILTER_LABELS = {
    "eligible": "Eligible",
    "unknown": "Unclear",
    "not_eligible": "Filtered out",
    "unchecked": "No profile yet",
}


def split_items(raw: str) -> list[str]:
    return [x.strip() for x in str(raw or "").replace("\n", ",").replace(";", ",").split(",") if x.strip()]


def render_profile():
    from jobsieve import profile as prof

    data, error = profile_request("GET")
    if error:
        st.error(error)
        return
    current = data["profile"]
    if not data["exists"]:
        st.info("Set your country and work rights so every job can be checked against them.")
    with st.form("profile_form"):
        left, right = st.columns(2)
        with left:
            home = st.text_input("Country you live in", value=current["home_country"], help="Name or code, e.g. Egypt or EG")
            authorization = st.text_input(
                "Where you can work without sponsorship",
                value=", ".join(current["work_authorization"]),
                help="Countries or regions, e.g. GCC, EU, Canada",
            )
            needs_visa = st.checkbox("I need visa sponsorship to work abroad", value=current["needs_visa"])
            relocation = st.text_input(
                "Countries you would relocate to", value=", ".join(current["open_to_relocation"])
            )
            modes = st.multiselect("Work modes", list(prof.WORK_MODES), default=current["work_modes"])
            seniority = st.multiselect("Seniority", list(prof.SENIORITY_LEVELS), default=current["seniority"])
        with right:
            floor = st.number_input("Minimum yearly pay (0 = any)", min_value=0.0, value=float(current["salary_floor"] or 0.0), step=1000.0)
            currency = st.text_input("Pay currency", value=current["salary_currency"])
            tz = st.text_input("Your UTC offset (e.g. 3)", value="" if current["timezone_offset"] is None else f"{current['timezone_offset']:g}")
            tz_diff = st.text_input("Largest timezone gap you accept, in hours", value="" if current["max_timezone_diff"] is None else f"{current['max_timezone_diff']:g}")
            dealbreakers = st.text_area("Dealbreaker words", value=", ".join(current["dealbreakers"]), height=70)
            excluded = st.text_area("Companies to skip", value=", ".join(current["excluded_companies"]), height=70)
        keywords = st.text_area("Roles and keywords to search", value=", ".join(current["keywords"]), height=70)
        cv = st.text_area("CV or profile text", value=current["cv_text"], height=200)
        if st.form_submit_button("Save profile"):
            payload = {
                "home_country": home,
                "work_authorization": split_items(authorization),
                "needs_visa": needs_visa,
                "open_to_relocation": split_items(relocation),
                "work_modes": modes,
                "seniority": seniority,
                "salary_floor": floor or None,
                "salary_currency": currency,
                "timezone_offset": tz or None,
                "max_timezone_diff": tz_diff or None,
                "dealbreakers": split_items(dealbreakers),
                "excluded_companies": split_items(excluded),
                "keywords": split_items(keywords),
                "cv_text": cv,
            }
            saved, error = profile_request("PUT", payload)
            if error:
                st.error(error)
            else:
                counts = saved["reevaluated"]
                st.success(
                    f"Saved. Saved jobs re-checked: {counts['eligible']} eligible, "
                    f"{counts['unknown']} unclear, {counts['not_eligible']} filtered out."
                )


def api_request(method: str, path: str, payload: dict | None = None):
    try:
        r = requests.request(method, f"{SCRAPER_URL}{path}", json=payload, headers=auth_headers(), timeout=30)
    except Exception as e:
        return None, f"cannot reach the API: {e}"
    if r.status_code >= 400:
        try:
            return None, str(r.json().get("detail") or r.text)
        except Exception:
            return None, r.text
    return r.json(), ""


def render_watchlist():
    st.caption(
        "Companies whose career boards are read directly. Select the 'boards' source in a run to include them. "
        "The name is the part of the board address after the site, e.g. careem in boards.greenhouse.io/careem."
    )
    data, error = api_request("GET", "/watchlist")
    if error:
        st.error(error)
        return
    starters, _ = api_request("GET", "/watchlist/starters")
    for name, info in ((starters or {}).get("lists") or {}).items():
        if st.button(f"Add the {name} starter list ({info['companies']} companies)", help=info["description"], key=f"starter-{name}"):
            added, error = api_request("POST", "/watchlist/starter", {"name": name})
            if error:
                st.error(error)
            else:
                st.success(f"{added['added']} companies added.")
                st.rerun()
    with st.form("watch_add", clear_on_submit=True):
        left, right = st.columns(2)
        board = left.selectbox("Board", data["boards"])
        company = right.text_input("Company name in the board address")
        if st.form_submit_button("Add (checks the board first)"):
            added, error = api_request("POST", "/watchlist", {"board": board, "company": company, "verify": True})
            if error:
                st.error(error)
            elif added["added"]:
                st.success(f"Added. {added['jobs_found']} open jobs found.")
                st.rerun()
            else:
                st.info("Already on the list.")
    for row in data["companies"]:
        name, button = st.columns([5, 1])
        name.write(f"{row['slug']}  ·  {row['board']}" + ("  ·  found by search" if row.get("added_by") == "discovered" else ""))
        if button.button("Remove", key=f"rm-{row['board']}-{row['slug']}"):
            api_request("DELETE", f"/watchlist/{row['board']}/{row['slug']}")
            st.rerun()
    if not data["companies"]:
        st.info("No companies yet.")


VIEWS = {
    "Inbox": ["new"],
    "Saved": ["saved"],
    "Applied": ["applied", "interviewing", "offer"],
    "Rejected": ["rejected"],
    "Hidden": ["hidden"],
    "All except hidden": None,
}


def change_status(job: dict, status: str):
    _, error = api_request("PATCH", f"/jobs/{job['job_hash']}", {"status": status})
    if error:
        st.error(error)
    else:
        st.rerun()


def hide_from_profile(field: str, value: str):
    data, error = profile_request("GET")
    if error:
        st.error(error)
        return
    current = data["profile"][field]
    if value.lower() in (x.lower() for x in current):
        st.info("Already in your profile.")
        return
    _, error = profile_request("PUT", {**data["profile"], field: current + [value]})
    if error:
        st.error(error)
    else:
        st.success(f"Added '{value}'. Saved jobs were re-checked.")


def render_first_run():
    data, error = profile_request("GET")
    if error or data["exists"]:
        return
    with st.container(border=True):
        st.subheader("Welcome to Jobsieve")
        st.markdown(
            "1. Open the **Profile** tab and save where you live and where you can work, so every job can be checked against it.\n"
            "2. Open the **Watchlist** tab and add the starter list, or companies you like.\n"
            "3. In the sidebar pick your sources (add `boards` for the watchlist and the job feeds), enter keywords, and press **Start**.\n\n"
            "Nothing leaves your machine unless you add an AI key or a notification address."
        )


def draft_application(job: dict):
    provider = st.session_state.get("provider", "groq")
    with st.expander("Draft application (CV suggestions and cover letter)"):
        saved = job.get("tailoring")
        if st.button("Write draft with " + provider, key=f"tailor-{job['job_hash']}"):
            data, error = api_request("POST", f"/jobs/{job['job_hash']}/tailor", {"provider": provider})
            if error:
                st.error(error)
            else:
                saved = data["tailoring"]
        if saved:
            if saved.get("unverified_numbers"):
                st.warning("Check before sending, these numbers are not in your CV or the listing: " + ", ".join(saved["unverified_numbers"]))
            st.markdown("**CV suggestions**\n" + "\n".join(f"- {x}" for x in saved["cv_suggestions"]))
            st.markdown("**Not shown in your CV**\n" + "\n".join(f"- {x}" for x in saved["keyword_gaps"]))
            st.text_area("Cover letter draft", saved["cover_letter"], height=220, key=f"letter-{job['job_hash']}")


def job_actions(job: dict):
    current = job.get("status") or "new"
    cols = st.columns(5)
    for column, (label, status) in zip(cols[:3], (("Save", "saved"), ("Applied", "applied"), ("Hide", "hidden"))):
        if column.button(label, key=f"{status}-{job['job_hash']}", disabled=current == status):
            change_status(job, status)
    if current in ("applied", "interviewing", "offer", "rejected"):
        step = cols[3].selectbox(
            "Stage", ["applied", "interviewing", "offer", "rejected"],
            index=["applied", "interviewing", "offer", "rejected"].index(current),
            key=f"stage-{job['job_hash']}", label_visibility="collapsed",
        )
        if step != current:
            change_status(job, step)
    if job.get("company") and cols[4].button("Hide company", key=f"co-{job['job_hash']}"):
        hide_from_profile("excluded_companies", job["company"])


def job_line(job: dict) -> str:
    parts = [job.get("company"), job.get("location"), job.get("salary")]
    if job.get("remote"):
        parts.append("remote")
    raw_source = job.get("source") or ""
    source = REGISTRY.get(raw_source)
    if raw_source.startswith("capture:"):
        parts.append(f"captured from {raw_source.split(':', 1)[1]}")
    elif source and source.name != "ddg":
        parts.append(f"via {source.label}")
    state = job.get("freshness") or {}
    if state.get("label") and state["label"] != "unknown":
        parts.append(f"{state['label']}: " + ", ".join(state.get("facts") or [])[:80] if state.get("facts") else state["label"])
    others = sorted({o.get("source") for o in job.get("also_seen") or [] if o.get("source")})
    if others:
        parts.append("also on " + ", ".join(others))
    return " · ".join(str(p) for p in parts if p)


def main():
    st.set_page_config(
        page_title="Jobsieve",
        page_icon="🧭",
        layout="wide",
    )
    db.init()

    st.title("Jobsieve")

    if "show_about" not in st.session_state:
        st.session_state.show_about = False

    with st.sidebar:
        st.header("Run")
        if st.button("About"):
            st.session_state.show_about = not bool(st.session_state.show_about)
        if st.session_state.show_about:
            st.markdown(
                "This app runs a job search and stores results in SQLite. "
                "You can run in Lite mode (keyword scoring) or use an AI provider key."
            )
        provider = st.selectbox(
            "AI Provider",
            options=["groq", "anthropic", "gemini", "openai"],
            index=0,
            key="provider",
            help="'openai' means any OpenAI-compatible server: OpenAI, OpenRouter, or a local model (Ollama, LM Studio). Set OPENAI_BASE_URL and OPENAI_MODEL on the server.",
        )
        groq_api_key = st.text_input("Groq API Key", type="password")
        anthropic_api_key = st.text_input("Anthropic API Key", type="password")
        gemini_api_key = st.text_input("Gemini API Key", type="password")
        provider_to_key = {
            "groq": groq_api_key,
            "anthropic": anthropic_api_key,
            "gemini": gemini_api_key,
        }
        server_keys = fetch_config()
        selected_key = provider_to_key.get(provider, "") or server_keys.get(provider)
        lite_mode = st.toggle("Lite Mode", value=False)
        sources = st.multiselect(
            "Sources",
            options=available_sources(),
            default=["ddg"],
            format_func=lambda name: REGISTRY[name].label,
            help="Web search needs sites and keywords. Job feeds are filtered by your keywords.",
        )
        st.divider()
        st.header("Inputs")
        default_sites = st.session_state.get("sites_raw", "")
        default_keywords = st.session_state.get("keywords_raw", "")
        default_cv = st.session_state.get("cv_text", "")
        sites_raw = st.text_area("Sites (one per line, optional)", value=default_sites, height=120)
        keywords_raw = st.text_area("Keywords (one per line)", value=default_keywords, height=160)
        cv_text = st.text_area("CV / Profile text", value=default_cv, height=180)
        st.session_state.sites_raw = sites_raw
        st.session_state.keywords_raw = keywords_raw
        st.session_state.cv_text = cv_text
        sites = parse_lines(sites_raw)
        keywords = parse_lines(keywords_raw)
        effective_lite = lite_mode or not bool(selected_key)
        key_source = "" if provider_to_key.get(provider) else " using the server key"
        mode_label = "Lite (keyword matching)" if effective_lite else f"AI ({provider}){key_source}"
        st.caption(f"Mode: {mode_label}")
        if st.button("Start"):
            ok, err = trigger(
                provider=provider,
                groq_api_key=groq_api_key,
                anthropic_api_key=anthropic_api_key,
                gemini_api_key=gemini_api_key,
                lite_mode=effective_lite,
                sites=sites,
                keywords=keywords,
                cv_text=cv_text,
                sources=sources,
            )
            if ok:
                st.success("Run started")
            else:
                st.error(f"Failed to start run: {err}")

        st.divider()
        st.header("Controls")
        cols = st.columns(3)
        if cols[0].button("Pause"):
            ok, err = control("pause")
            if not ok:
                st.error(err)
        if cols[1].button("Resume"):
            ok, err = control("resume")
            if not ok:
                st.error(err)
        if cols[2].button("Stop"):
            ok, err = control("stop")
            if not ok:
                st.error(err)

        if st.button("Restart Run"):
            control("stop")
            for _ in range(40):
                s = fetch_status()
                if not bool(s.get("running", False)):
                    break
                time.sleep(0.25)
            ok, err = trigger(
                provider=provider,
                groq_api_key=groq_api_key,
                anthropic_api_key=anthropic_api_key,
                gemini_api_key=gemini_api_key,
                lite_mode=effective_lite,
                sites=sites,
                keywords=keywords,
                cv_text=cv_text,
                sources=sources,
            )
            if ok:
                st.success("Run restarted")
            else:
                st.error(f"Failed to restart run: {err}")

    tab_jobs, tab_profile, tab_watch = st.tabs(["Jobs", "Profile", "Watchlist"])
    with tab_profile:
        render_profile()
    with tab_watch:
        render_watchlist()
    with tab_jobs:
        render_first_run()
        col1, col2 = st.columns([1, 2])
        with col1:
            status = fetch_status()
            st.metric("Status", status.get("message", ""))
            st.progress(int(status.get("progress", 0)) / 100)
            st.metric("Running", bool(status.get("running", False)))
            st.metric("Paused", bool(status.get("paused", False)))
            st.metric("Added", int(status.get("added", 0) or 0))
            if int(status.get("ai_failed", 0) or 0):
                st.warning(f"AI scoring failed for {status['ai_failed']} listings; keyword scores used.")
            if st.button("Refresh"):
                st.rerun()

        with col2:
            latest_only = st.toggle("Latest run only", value=True)
            shown = st.multiselect(
                "Show",
                options=list(FILTER_LABELS),
                default=["eligible", "unknown", "unchecked"],
                format_func=lambda key: FILTER_LABELS[key],
            )
            last_visit = db.get_meta("last_visit", "")
            fresh = db.count_new_since(last_visit) if last_visit else 0
            if fresh:
                note, button = st.columns([4, 1])
                note.info(f"{fresh} new eligible jobs since your last visit.")
                if button.button("Mark as seen"):
                    db.set_meta("last_visit", datetime.now(timezone.utc).isoformat())
                    st.rerun()
            elif not last_visit:
                db.set_meta("last_visit", datetime.now(timezone.utc).isoformat())
            view = st.radio("View", list(VIEWS), horizontal=True)
            latest_run = db.latest_run_id() if latest_only and view in ("Inbox", "All except hidden") else None
            jobs = db.list_jobs(
                limit=200, run_id=latest_run, status=VIEWS[view],
                eligibility=None if len(shown) == len(FILTER_LABELS) else shown or ["none"],
            )
            total_jobs = db.count_jobs()
            st.metric("Jobs", total_jobs)
            if len(jobs) < total_jobs:
                scope = "latest run" if latest_run else "all runs"
                st.caption(f"Showing top {len(jobs)} of {total_jobs} ({scope})")
            if not jobs:
                st.info("No jobs yet. Add keywords in the sidebar and hit Start.")
            for j in jobs:
                with st.container(border=True):
                    score_val = int(j.get("score") or 0)
                    tier = "green" if score_val >= 7 else "orange" if score_val >= 4 else "gray"
                    top = st.columns([4, 1])
                    with top[0]:
                        st.subheader(j.get("title") or "")
                    with top[1]:
                        st.markdown(f":{tier}[**{score_val}/10**]")
                    verdict = VERDICT_LABELS.get(j.get("eligibility") or "")
                    if verdict:
                        reasons = j.get("eligibility_reasons") or []
                        st.markdown(verdict + (": " + "; ".join(reasons) if reasons else ""))
                    st.caption(job_line(j))
                    st.caption(j.get("link") or "")
                    st.write(j.get("snippet") or "")
                    job_actions(j)
                    draft_application(j)
                    if j.get("reasoning"):
                        prefix = ":red[AI failed] " if str(j["reasoning"]).startswith("ai_failed:") else ""
                        st.caption(prefix + j.get("reasoning"))

    if bool(status.get("running", False)):
        time.sleep(1.5)
        st.rerun()


if __name__ == "__main__":
    main()
