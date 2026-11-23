import os
import time
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
            options=["groq", "anthropic", "gemini"],
            index=0,
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

    tab_jobs, tab_profile = st.tabs(["Jobs", "Profile"])
    with tab_profile:
        render_profile()
    with tab_jobs:
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
            latest_run = db.latest_run_id() if latest_only else None
            jobs = db.list_jobs(limit=200, run_id=latest_run, eligibility=None if len(shown) == len(FILTER_LABELS) else shown or ["none"])
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
                    if j.get("reasoning"):
                        prefix = ":red[AI failed] " if str(j["reasoning"]).startswith("ai_failed:") else ""
                        st.caption(prefix + j.get("reasoning"))

    if bool(status.get("running", False)):
        time.sleep(1.5)
        st.rerun()


if __name__ == "__main__":
    main()
