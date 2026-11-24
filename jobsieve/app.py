import os

import streamlit as st

from jobsieve.ui import pages
from jobsieve.ui.components import show_flash

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
# Streamlit drops a widget's value when its page is left, so these are re-assigned on every run.
KEPT = (
    "run_keywords", "run_sources", "run_sites", "run_mode", "provider", "key_groq", "key_anthropic", "key_gemini",
    "view", "verdicts", "latest_only", "filter_text",
)


def main():
    st.set_page_config(page_title="Jobsieve", page_icon=os.path.join(DATA, "icon.svg"), layout="wide")
    for key in KEPT:
        if key in st.session_state:
            st.session_state[key] = st.session_state[key]
    st.logo(os.path.join(DATA, "logo.svg"), size="large")
    page = st.navigation([
        st.Page(pages.jobs_page, title="Jobs", icon=":material/work:", url_path="jobs", default=True),
        st.Page(pages.search_page, title="Search", icon=":material/search:", url_path="search"),
        st.Page(pages.profile_page, title="Profile", icon=":material/person:", url_path="profile"),
        st.Page(pages.watchlist_page, title="Watchlist", icon=":material/domain:", url_path="watchlist"),
    ])
    st.sidebar.caption("Runs on your computer. Verdicts are rule-based and can be wrong, so check the listing before you apply.")
    show_flash()
    page.run()


main()
