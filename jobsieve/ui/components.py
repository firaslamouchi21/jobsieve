import re
from datetime import datetime

import streamlit as st

from jobsieve.sources import REGISTRY
from jobsieve.ui import client

VERDICTS = {
    "eligible": ("Eligible", ":material/check_circle:", "green"),
    "unknown": ("Unclear", ":material/help:", "orange"),
    "not_eligible": ("Not eligible", ":material/block:", "red"),
    "unchecked": ("Not checked", ":material/pending:", "gray"),
}
STATUS_LABELS = {
    "new": "New", "saved": "Saved", "applied": "Applied", "interviewing": "Interviewing",
    "offer": "Offer", "rejected": "Rejected", "hidden": "Hidden",
}
PROVIDERS = {"groq": "Groq", "anthropic": "Anthropic", "gemini": "Gemini", "openai": "OpenAI-compatible or local"}
SOURCE_LABELS = {
    "greenhouse": "Greenhouse", "lever": "Lever", "ashby": "Ashby", "smartrecruiters": "SmartRecruiters", "web": "Listed page",
}
MARKDOWN = re.compile(r"([\\`*_{}\[\]()<>#+!|~$:])")


def plain(text) -> str:
    """Listings are untrusted text, so none of it may be read as Markdown."""
    return MARKDOWN.sub(r"\\\1", " ".join(str(text or "").split()))


def safe_link(url) -> str:
    url = str(url or "")
    return url if url.startswith(("http://", "https://")) else ""


def header(title: str, subtitle: str):
    st.title(title, anchor=False)
    st.caption(subtitle)


def flash(message: str):
    st.session_state["_flash"] = message
    st.rerun()


def show_flash():
    message = st.session_state.pop("_flash", "")
    if message:
        st.toast(message, icon=":material/check:")


def source_label(source: str) -> str:
    if source.startswith("capture:"):
        return f"Captured from {source.split(':', 1)[1]}"
    if source in REGISTRY:
        return REGISTRY[source].label
    return SOURCE_LABELS.get(source, source)


def posted(job: dict) -> str:
    facts = (job.get("freshness") or {}).get("facts") or []
    return next((f[0].upper() + f[1:] for f in facts if f.startswith(("posted", "first seen"))), "")


def job_meta(job: dict) -> str:
    place = job.get("location") or ""
    parts = [job.get("company"), place, job.get("salary"), posted(job), source_label(job.get("source") or "")]
    if job.get("remote") and "remote" not in place.lower():
        parts.insert(2, "Remote")
    return " · ".join(plain(p) for p in parts if p)


def change_status(job: dict, status: str):
    _, error = client.call("PATCH", f"/jobs/{job['job_hash']}", {"status": status})
    if error:
        st.error(error)
    else:
        flash(f"Moved to {STATUS_LABELS[status].lower()}")


def skip_company(job: dict):
    data, error = client.call("GET", "/profile")
    if error:
        st.error(error)
        return
    current = data["profile"]["excluded_companies"]
    if job["company"].lower() not in (x.lower() for x in current):
        _, error = client.call("PUT", "/profile", {**data["profile"], "excluded_companies": current + [job["company"]]}, timeout=120)
        if error:
            st.error(error)
            return
    flash(f"{job['company']} added to the companies you skip")


def details(job: dict):
    key = job["job_hash"]
    reasons = job.get("eligibility_reasons") or []
    if reasons:
        st.markdown("**Eligibility**")
        st.markdown("\n".join(f"- {plain(r)}" for r in reasons))
    facts = (job.get("freshness") or {}).get("facts") or []
    if facts:
        st.markdown("**Dates**")
        st.markdown("\n".join(f"- {plain(f[0].upper() + f[1:])}" for f in facts))
    others = [o for o in job.get("also_seen") or [] if o.get("source")]
    if others:
        st.markdown("**Also listed on**")
        st.markdown("\n".join(f"- {plain(source_label(o['source']))}" for o in others))
    if job.get("reasoning"):
        st.markdown("**Score**")
        failed = str(job["reasoning"]).startswith("ai_failed:")
        st.caption(("AI scoring failed, so this is the keyword score. " if failed else "") + plain(job["reasoning"]))
    if job.get("description"):
        st.markdown("**Description**")
        st.text(str(job["description"])[:4000])
    with st.form(f"notes-{key}", border=False):
        notes = st.text_area("Notes", value=job.get("notes") or "", max_chars=2000, height=80)
        if st.form_submit_button("Save notes"):
            _, error = client.call("PATCH", f"/jobs/{key}", {"notes": notes})
            st.error(error) if error else flash("Notes saved")
    draft(job)


def draft(job: dict):
    key = job["job_hash"]
    provider = st.session_state.get("provider", "groq")
    st.markdown("**Application draft**")
    if st.button(f"Write a draft with {PROVIDERS[provider]}", key=f"tailor-{key}", icon=":material/edit_note:"):
        with st.spinner("Writing the draft"):
            _, error = client.tailor(key, provider, st.session_state.get(f"key_{provider}", ""))
        if error:
            st.error(error)
        else:
            flash("Draft saved")
    saved = job.get("tailoring")
    if not saved:
        st.caption("CV suggestions, missing requirements and a cover letter, based only on the CV in your profile.")
        return
    if saved.get("unverified_numbers"):
        st.warning("Check before sending. Not in your CV or the listing: " + plain(", ".join(saved["unverified_numbers"])))
    for title, field in (("CV suggestions", "cv_suggestions"), ("Not shown in your CV", "keyword_gaps")):
        if saved.get(field):
            st.markdown(f"{title}\n" + "\n".join(f"- {plain(x)}" for x in saved[field]))
    st.text_area("Cover letter", saved.get("cover_letter") or "", height=220, key=f"letter-{key}")


def job_card(job: dict):
    key, current = job["job_hash"], job.get("status") or "new"
    # The key ties an open menu to its job; without it the menu stays open on the next card.
    with st.container(border=True, key=f"card-{key}"):
        text, score = st.columns([8, 1], vertical_alignment="top")
        text.markdown(f"#### {plain(job.get('title'))}\n:gray[{job_meta(job)}]")
        value = job.get("score")
        score.markdown(f"**{value if value is not None else '–'}** / 10", width="content")
        label, icon, color = VERDICTS[job.get("eligibility") or "unchecked"]
        with st.container(horizontal=True, vertical_alignment="center"):
            st.badge(label, icon=icon, color=color)
            fresh = (job.get("freshness") or {}).get("label")
            if fresh in ("new", "stale", "closed"):
                st.badge({"new": "New", "stale": "Over 45 days old", "closed": "Closed"}[fresh], color="blue" if fresh == "new" else "gray")
            if current != "new":
                st.badge(STATUS_LABELS[current], color="blue")
            reasons = job.get("eligibility_reasons") or []
            if reasons:
                st.caption(plain(reasons[0][0].upper() + reasons[0][1:]) + (f" (+{len(reasons) - 1} more)" if len(reasons) > 1 else ""), width="content")
        with st.container(horizontal=True, vertical_alignment="center"):
            if safe_link(job.get("link")):
                st.link_button("Open listing", safe_link(job["link"]), icon=":material/open_in_new:")
            if current != "saved":
                if st.button("Save", key=f"saved-{key}", icon=":material/bookmark:"):
                    change_status(job, "saved")
            if current not in ("applied", "interviewing", "offer", "rejected"):
                if st.button("Mark applied", key=f"applied-{key}", icon=":material/send:"):
                    change_status(job, "applied")
            with st.popover("More"):
                for status, name in STATUS_LABELS.items():
                    if status not in (current, "saved", "applied") and st.button(f"Move to {name.lower()}", key=f"{status}-{key}", width="stretch"):
                        change_status(job, status)
                if job.get("company") and st.button("Skip this company", key=f"co-{key}", width="stretch"):
                    skip_company(job)
            show = st.toggle("Details", key=f"open-{key}")
        if show:
            details(job)


def run_summary(status: dict):
    message = status.get("message", "")
    if message == "offline":
        st.error("The Jobsieve API is not answering. Start it with 'jobsieve start'.", icon=":material/cloud_off:")
        return
    if status.get("running"):
        percent = max(0, min(100, int(status.get("progress") or 0)))
        st.progress(percent / 100, text=f"{'Paused' if status.get('paused') else 'Searching'}: {percent}%, {int(status.get('added') or 0)} new")
        return
    finished = status.get("timestamp")
    when = datetime.fromtimestamp(finished).strftime("%d %b, %H:%M") if finished else ""
    text = {
        "idle": "No search has run yet.",
        "complete": f"Last search finished {when}. {int(status.get('added') or 0)} new listings.",
        "stopped": f"Last search was stopped {when}.",
        "interrupted": "The last search was interrupted. Start it again when ready.",
        "no_keywords": "The last search had no keywords. Add some and start again.",
        "invalid_sources": "The last search used a source that does not exist.",
    }.get(message, message)
    st.caption(text)
    if int(status.get("ai_failed") or 0):
        st.warning(f"AI scoring failed for {status['ai_failed']} listings, so they have keyword scores.")
