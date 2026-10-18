"""Dashboard — overview of the job search."""

from __future__ import annotations

import streamlit as st

from src.ui.components import Step, empty_state, page_header, section_header, steps
from src.pages.find_jobs import SEARCH_PREFILL_KEY
from src.ui.navigation import go_to


def _quick_search() -> None:
    with st.container(border=True):
        st.markdown("##### Start a job search")
        with st.form("dashboard_quick_search", border=False):
            c1, c2, c3 = st.columns([5, 3, 2], vertical_alignment="bottom")
            query = c1.text_input("Job title or keywords", placeholder="e.g. Quality Engineer")
            location = c2.text_input("Location", placeholder="City, country or Remote")
            submitted = c3.form_submit_button(
                "Search jobs", type="primary", icon=":material/search:", width="stretch"
            )
        if submitted:
            if not query.strip():
                st.error("Enter a job title or keywords to search.")
            else:
                st.session_state[SEARCH_PREFILL_KEY] = {"query": query.strip(), "location": location.strip()}
                go_to("find-jobs")


def render() -> None:
    page_header(
        "Welcome to CareerMatch AI",
        "Upload your CV, discover relevant vacancies and see — with evidence — how well each one fits.",
        eyebrow="Dashboard",
    )
    _quick_search()

    section_header("Getting started", "Complete these steps to unlock matching, research and tracking.")
    steps([
        Step("Upload your CV", "Add a PDF or DOCX CV. It stays on this computer."),
        Step("Review your CV analysis", "See structure, ATS compatibility and prioritised improvements."),
        Step("Search for jobs", "Query the job sources you have configured in Settings."),
        Step("Review ranked matches", "Inspect evidence, missing requirements and recommendations."),
        Step("Prepare and track", "Research employers, prepare for interviews and track applications."),
    ])

    section_header("Your activity")
    empty_state(
        "No activity yet",
        "Metrics such as jobs analysed, strong matches, applications and interviews appear here once "
        "you have searched for and saved jobs. Nothing is shown until it is based on your real data.",
    )
