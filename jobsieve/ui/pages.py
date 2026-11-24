import streamlit as st

from jobsieve import profile as prof
from jobsieve.sources import REGISTRY, available_sources
from jobsieve.ui import client
from jobsieve.ui.components import PROVIDERS, VERDICTS, flash, header, job_card, plain, run_summary

VIEWS = {
    "Inbox": ["new"],
    "Saved": ["saved"],
    "Applied": ["applied", "interviewing", "offer"],
    "Rejected": ["rejected"],
    "Hidden": ["hidden"],
}
PAGE_SIZE = 20
KEY_PROVIDERS = ("groq", "anthropic", "gemini")


def split_items(raw: str) -> list[str]:
    return [x.strip() for x in str(raw or "").replace("\n", ",").replace(";", ",").split(",") if x.strip()]


@st.fragment(run_every=2)
def live_status():
    status = client.status()
    run_summary(status)
    was_running = st.session_state.get("_was_running", False)
    st.session_state["_was_running"] = bool(status.get("running"))
    if was_running and not status.get("running"):
        st.rerun(scope="app")


def status_panel():
    status = client.status()
    if status.get("running"):
        st.session_state["_was_running"] = True
        live_status()
    else:
        st.session_state["_was_running"] = False
        run_summary(status)
    return status


def getting_started():
    data, error = client.call("GET", "/profile")
    if error or data["exists"]:
        return
    with st.container(border=True):
        st.subheader("Get started", anchor=False)
        st.markdown(
            "1. **Profile.** Say where you live and where you can work, so every job can be checked.\n"
            "2. **Watchlist.** Add a starter list or the companies you care about.\n"
            "3. **Search.** Choose your sources and start."
        )
        st.caption("Your data stays on this computer unless you add an AI key or a notification address.")


def jobs_page():
    header("Jobs", "Listings checked against your profile, best matches first.")
    status_panel()
    getting_started()
    summary, error = client.call("GET", "/summary")
    if error:
        st.error(error)
        return
    by_status, verdicts = summary["by_status"], summary["inbox_by_eligibility"]
    with st.container(horizontal=True, vertical_alignment="center"):
        for verdict, (label, icon, color) in VERDICTS.items():
            if verdicts.get(verdict):
                st.badge(f"{verdicts[verdict]} {label.lower()}", icon=icon, color=color)
    if summary["new_since_visit"]:
        with st.container(horizontal=True, vertical_alignment="center"):
            st.markdown(f"**{summary['new_since_visit']}** new eligible since your last visit.")
            if st.button("Mark as seen"):
                client.call("POST", "/visit")
                st.rerun()

    st.session_state.setdefault("view", "Inbox")
    st.session_state.setdefault("verdicts", ["eligible", "unknown", "unchecked"])

    def view_label(name):
        return f"{name} ({sum(by_status.get(s, 0) for s in VIEWS[name])})"

    view = st.segmented_control("View", list(VIEWS), format_func=view_label, key="view", label_visibility="collapsed") or "Inbox"
    search, chosen, scope = st.columns([3, 4, 2], vertical_alignment="bottom")
    text = search.text_input("Filter", placeholder="Title, company or place", key="filter_text").strip().lower()
    picked = chosen.pills(
        "Eligibility", list(VERDICTS), selection_mode="multi",
        format_func=lambda v: VERDICTS[v][0], key="verdicts",
    )
    latest = scope.toggle("Latest search only", key="latest_only", disabled=view != "Inbox")
    jobs, error = client.jobs(VIEWS[view], picked or list(VERDICTS), latest_run=latest and view == "Inbox")
    if error:
        st.error(error)
        return
    if text:
        jobs = [j for j in jobs if text in f"{j.get('title')} {j.get('company')} {j.get('location')}".lower()]
    if not jobs:
        st.info("Nothing here yet." if not (text or len(picked) < len(VERDICTS)) else "No jobs match these filters.")
        return
    pages = (len(jobs) - 1) // PAGE_SIZE + 1
    count, pager = st.columns([5, 1], vertical_alignment="center")
    page = min(int(pager.number_input("Page", 1, pages, 1, key=f"page-{view}", label_visibility="collapsed")), pages) if pages > 1 else 1
    count.caption(f"{len(jobs)} jobs" + (f", page {page} of {pages}" if pages > 1 else ""))
    for job in jobs[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]:
        job_card(job)


def control(action: str):
    _, error = client.call("POST", f"/{action}", timeout=5)
    st.error(error) if error else st.rerun()


def search_page():
    header("Search", "Choose where to look and how to score what comes back.")
    status = status_panel()
    if status.get("running"):
        with st.container(horizontal=True):
            if status.get("paused"):
                if st.button("Resume", icon=":material/play_arrow:"):
                    control("resume")
            elif st.button("Pause", icon=":material/pause:"):
                control("pause")
            if st.button("Stop", icon=":material/stop:"):
                control("stop")
    data, error = client.call("GET", "/profile")
    if error:
        st.error(error)
        return
    profile = data["profile"]
    known = available_sources()
    defaults = {
        "run_mode": "Keywords",
        "run_sources": [s for s in profile["sources"] if s in known] or ["ddg"],
        "run_keywords": "\n".join(profile["keywords"]),
        "run_sites": "\n".join(profile["sites"]),
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)
    with st.container(border=True):
        st.subheader("What to look for", anchor=False)
        left, right = st.columns(2)
        left.text_area("Keywords, one per line", key="run_keywords", height=130)
        right.multiselect("Sources", known, key="run_sources", format_func=lambda n: REGISTRY[n].label)
        if "ddg" in st.session_state["run_sources"]:
            right.text_area("Sites for web search, one per line (optional)", key="run_sites", height=80)
        if not profile["cv_text"]:
            st.caption("Add your CV on the Profile page so scores take it into account.")
    with st.container(border=True):
        st.subheader("Scoring", anchor=False)
        mode = st.segmented_control("Scoring mode", ["Keywords", "AI"], key="run_mode", label_visibility="collapsed") or "Keywords"
        provider, ready = "groq", True
        if mode == "AI":
            left, right = st.columns(2)
            provider = left.selectbox("Provider", list(PROVIDERS), format_func=PROVIDERS.get, key="provider")
            server, _ = client.call("GET", "/config", timeout=5)
            on_server = bool(((server or {}).get("providers") or {}).get(provider))
            if provider in KEY_PROVIDERS:
                right.text_input(
                    f"{PROVIDERS[provider]} API key", type="password", key=f"key_{provider}",
                    placeholder="Using the server key" if on_server else "", help="Used for this session and never written to disk.",
                )
                ready = on_server or bool(st.session_state.get(f"key_{provider}"))
            else:
                ready = on_server
                right.caption("Set OPENAI_MODEL, and OPENAI_BASE_URL for a local model, where the API runs.")
            if not ready:
                st.warning("This provider has no key or model yet.")
        else:
            st.caption("Free and offline: counts your keywords and the CV terms found in each listing.")
    keywords = split_items(st.session_state["run_keywords"])
    blocked = bool(status.get("running")) or not keywords or not st.session_state["run_sources"] or not ready
    if st.button("Start search", type="primary", icon=":material/search:", disabled=blocked):
        payload = {
            "provider": provider, "lite_mode": mode != "AI", "keywords": keywords,
            "sources": st.session_state["run_sources"], "sites": split_items(st.session_state.get("run_sites")),
            "cv_text": profile["cv_text"] or None,
        }
        for name in KEY_PROVIDERS:
            payload[f"{name}_api_key"] = st.session_state.get(f"key_{name}", "") if mode == "AI" else ""
        result, error = client.call("POST", "/run", payload, timeout=10)
        if error:
            st.error(error)
        elif not result.get("started"):
            st.warning("A search is already running.")
        else:
            st.session_state["_was_running"] = True
            flash("Search started")
    if not keywords:
        st.caption("Add at least one keyword to start.")


def profile_page():
    header("Profile", "Every job is checked against this. It stays on this computer.")
    data, error = client.call("GET", "/profile")
    if error:
        st.error(error)
        return
    current = data["profile"]

    def number(value):
        return "" if value is None else f"{value:g}"

    with st.form("profile_form", border=False):
        with st.container(border=True):
            st.subheader("Where you can work", anchor=False)
            left, right = st.columns(2)
            home = left.text_input("Country you live in", current["home_country"], help="Name or code, e.g. Egypt or EG")
            rights = right.text_input("Where you can work without sponsorship", ", ".join(current["work_authorization"]), help="Countries or regions, e.g. GCC, EU, Canada")
            relocation = left.text_input("Where you would relocate", ", ".join(current["open_to_relocation"]))
            zone = right.text_input("Your UTC offset", number(current["timezone_offset"]), placeholder="3")
            gap = right.text_input("Largest timezone gap you accept, in hours", number(current["max_timezone_diff"]))
            needs_visa = left.checkbox("I need visa sponsorship to work abroad", current["needs_visa"])
        with st.container(border=True):
            st.subheader("What you want", anchor=False)
            left, right = st.columns(2)
            keywords = left.text_area("Roles and keywords", ", ".join(current["keywords"]), height=80)
            modes = right.multiselect("Work modes", list(prof.WORK_MODES), current["work_modes"], format_func=str.capitalize)
            seniority = right.multiselect("Seniority", list(prof.SENIORITY_LEVELS), current["seniority"], format_func=str.capitalize)
            floor = left.number_input("Minimum yearly pay (0 for any)", 0.0, None, float(current["salary_floor"] or 0.0), 1000.0)
            currency = right.text_input("Currency", current["salary_currency"])
        with st.container(border=True):
            st.subheader("What to skip", anchor=False)
            left, right = st.columns(2)
            dealbreakers = left.text_area("Dealbreaker words", ", ".join(current["dealbreakers"]), height=80)
            excluded = right.text_area("Companies", ", ".join(current["excluded_companies"]), height=80)
        with st.container(border=True):
            st.subheader("CV", anchor=False)
            cv = st.text_area("CV text", current["cv_text"], height=220, label_visibility="collapsed")
        if not st.form_submit_button("Save profile", type="primary"):
            return
    saved, error = client.call("PUT", "/profile", {
        **current,
        "home_country": home, "work_authorization": split_items(rights), "needs_visa": needs_visa,
        "open_to_relocation": split_items(relocation), "work_modes": modes, "seniority": seniority,
        "salary_floor": floor or None, "salary_currency": currency, "timezone_offset": zone or None,
        "max_timezone_diff": gap or None, "dealbreakers": split_items(dealbreakers),
        "excluded_companies": split_items(excluded), "keywords": split_items(keywords), "cv_text": cv,
    }, timeout=120)
    if error:
        st.error(error)
        return
    counts = saved["reevaluated"]
    st.success(f"Saved. Jobs re-checked: {counts['eligible']} eligible, {counts['unknown']} unclear, {counts['not_eligible']} not eligible.")


ORIGINS = {"manual": "Added by you", "discovered": "Found by search", "career page": "From a careers page", "agent": "Added by an agent"}


def watchlist_page():
    header("Watchlist", "Companies whose own career boards are read directly.")
    data, error = client.call("GET", "/watchlist")
    if error:
        st.error(error)
        return
    starters, _ = client.call("GET", "/watchlist/starters")
    add, page = st.columns(2)
    with add, st.form("watch_add", clear_on_submit=True):
        st.subheader("Add a company", anchor=False)
        board = st.selectbox("Board", data["boards"], format_func=str.capitalize)
        company = st.text_input("Name in the board address", placeholder="careem", help="For boards.greenhouse.io/careem the name is careem")
        if st.form_submit_button("Add company", type="primary"):
            result, error = client.call("POST", "/watchlist", {"board": board, "company": company, "verify": True})
            if error:
                st.error(error)
            else:
                flash(f"Added, {result['jobs_found']} open jobs" if result["added"] else "Already on the list")
    with page, st.form("watch_page", clear_on_submit=True):
        st.subheader("Find it from a careers page", anchor=False)
        url = st.text_input("Careers page address", placeholder="https://company.com/careers")
        st.caption("Reads the page once and looks for the job board behind it.")
        if st.form_submit_button("Find board"):
            result, error = client.call("POST", "/watchlist/from-page", {"url": url})
            if error:
                st.error(error)
            elif not result["companies"]:
                st.warning("No supported job board found on that page.")
            else:
                flash(f"{sum(c['added'] for c in result['companies'])} added")
    for name, info in ((starters or {}).get("lists") or {}).items():
        with st.container(border=True, horizontal=True, vertical_alignment="center"):
            st.markdown(f"**Starter list: {plain(name)}**, {info['companies']} companies")
            if st.button("Add this list", key=f"starter-{name}", help=info["description"]):
                result, error = client.call("POST", "/watchlist/starter", {"name": name})
                st.error(error) if error else flash(f"{result['added']} companies added")
    st.subheader(f"Companies ({len(data['companies'])})", anchor=False)
    if not data["companies"]:
        st.info("No companies yet.")
    for row in data["companies"]:
        name, board, origin, button = st.columns([4, 3, 3, 1], vertical_alignment="center")
        name.markdown(f"**{plain(row['slug'])}**")
        board.caption(row["board"].capitalize())
        added_by = row.get("added_by", "manual")
        origin.caption("Starter list" if added_by.startswith("starter:") else ORIGINS.get(added_by, added_by))
        if button.button("", key=f"rm-{row['board']}-{row['slug']}", icon=":material/delete:", help=f"Remove {row['slug']}"):
            _, error = client.call("DELETE", f"/watchlist/{row['board']}/{row['slug']}")
            st.error(error) if error else flash("Removed")
