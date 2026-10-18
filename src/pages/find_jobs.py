"""Find Jobs — search configured job sources."""

from __future__ import annotations

import streamlit as st

from src.ui.components import notice, page_header

SEARCH_PREFILL_KEY = "cm_search_prefill"
_FORM_KEYS = ("fj_query", "fj_location", "fj_arrangement", "fj_level", "fj_type",
              "fj_posted", "fj_required", "fj_preferred", "fj_industry", "fj_salary")

WORK_ARRANGEMENTS = ["Any", "Remote", "Hybrid", "On-site"]
EXPERIENCE_LEVELS = ["Any", "Internship", "Entry level", "Mid level", "Senior", "Lead / Principal",
                     "Manager", "Director / Executive"]
EMPLOYMENT_TYPES = ["Any", "Full-time", "Part-time", "Contract", "Temporary", "Internship"]
DATE_POSTED = ["Any time", "Past 24 hours", "Past 3 days", "Past week", "Past month"]


def validate_search(query: str) -> list[str]:
    errors = []
    if not query.strip():
        errors.append("Enter a job title or keywords.")
    elif len(query.strip()) < 2:
        errors.append("Search keywords must be at least 2 characters.")
    elif len(query) > 200:
        errors.append("Search keywords must be 200 characters or fewer.")
    return errors


def _apply_prefill() -> None:
    prefill = st.session_state.pop(SEARCH_PREFILL_KEY, None)
    if prefill:
        st.session_state["fj_query"] = prefill.get("query", "")
        st.session_state["fj_location"] = prefill.get("location", "")
        st.session_state["fj_submitted"] = True


def _reset() -> None:
    for key in (*_FORM_KEYS, "fj_submitted"):
        st.session_state.pop(key, None)


def render() -> None:
    page_header(
        "Find Jobs",
        "Search the job sources you have configured. Results are always attributed to the source that returned them.",
        eyebrow="Discover",
    )
    _apply_prefill()

    with st.container(border=True):
        with st.form("job_search", border=False):
            c1, c2 = st.columns([3, 2])
            c1.text_input("Job title or keywords", key="fj_query", placeholder="e.g. Data Analyst, Python, SQL")
            c2.text_input("Location", key="fj_location", placeholder="City, country or Remote")
            c3, c4, c5, c6 = st.columns(4)
            c3.selectbox("Work arrangement", WORK_ARRANGEMENTS, key="fj_arrangement")
            c4.selectbox("Experience level", EXPERIENCE_LEVELS, key="fj_level")
            c5.selectbox("Employment type", EMPLOYMENT_TYPES, key="fj_type")
            c6.selectbox("Date posted", DATE_POSTED, key="fj_posted")
            with st.expander("More filters"):
                m1, m2 = st.columns(2)
                m1.text_input("Required skills", key="fj_required", placeholder="Comma-separated")
                m2.text_input("Preferred skills", key="fj_preferred", placeholder="Comma-separated")
                m3, m4 = st.columns(2)
                m3.text_input("Industry", key="fj_industry", placeholder="e.g. Manufacturing")
                m4.number_input("Minimum salary (where the source supports it)", key="fj_salary",
                                min_value=0, step=1000, value=None, placeholder="No minimum")
            b1, b2, _ = st.columns([1, 1, 4])
            searched = b1.form_submit_button("Search", type="primary", icon=":material/search:",
                                             width="stretch")
            b2.form_submit_button("Reset", on_click=_reset, icon=":material/restart_alt:",
                                  width="stretch")

    if searched:
        st.session_state["fj_submitted"] = True

    if st.session_state.get("fj_submitted"):
        errors = validate_search(st.session_state.get("fj_query", ""))
        if errors:
            for e in errors:
                st.error(e, icon=":material/error:")
        else:
            notice(
                "No job sources are connected yet, so this search was not sent anywhere. "
                "Job-source integrations are being added; once a source is configured in Settings, "
                "real results will appear here with their source and original listing link.",
                tone="info",
                title="No job sources configured.",
            )
