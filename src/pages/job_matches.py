"""Job Matches — ranked, explainable opportunities."""

from __future__ import annotations

import streamlit as st

from config.settings import get_settings
from src.cv.session import get_active_cv
from src.matching.engine import MATCH_LIMITATIONS
from src.pages.find_jobs import OUTCOME_KEY
from src.services.matching import ranked_matches
from src.ui.components import Feature, notice, page_header, section_header
from src.ui.layouts import call_to_action, empty_page_body
from src.ui.match_cards import match_card_html, render_breakdown

_FEATURES = [
    Feature("Explainable scores", "Required skills, experience, responsibilities, education and "
            "keywords are scored separately using configurable weights."),
    Feature("Recommendations", "APPLY, APPLY AFTER IMPROVEMENT or DON'T PRIORITIZE — guidance for "
            "prioritising, not a prediction of being hired."),
    Feature("Mandatory requirements", "A clearly essential qualification that your CV does not "
            "evidence is flagged, even when the overall score is high."),
]


def render() -> None:
    page_header(
        "Job Matches",
        "Jobs ranked by estimated compatibility with your CV, with the evidence behind every score.",
        eyebrow="Discover",
    )
    cv = get_active_cv(st.session_state)
    outcome = st.session_state.get(OUTCOME_KEY)

    if cv is None:
        empty_page_body(
            empty_title="Upload your CV first",
            empty_message="Matches compare your CV with job descriptions. Upload a CV, then search for jobs.",
            cta_label="Upload CV", cta_target="cv-analysis", cta_key="jm_cta_cv",
            features_title="How matching works", features=_FEATURES,
        )
        return
    if cv.extraction.needs_ocr or not cv.extraction.text.strip():
        notice("Your CV's text could not be read, so it cannot be matched with jobs. Upload a text-based PDF or "
               "DOCX on the CV Analysis page.", tone="warning")
        call_to_action("Go to CV Analysis", "cv-analysis", key="jm_cta_ocr")
        return
    if outcome is None or not outcome.unique_jobs:
        empty_page_body(
            empty_title="No jobs to match yet",
            empty_message="Search for jobs and they will be ranked here against your CV, with a score breakdown, "
                          "matching evidence and missing requirements for each.",
            cta_label="Find jobs", cta_target="find-jobs", cta_key="jm_cta",
            features_title="How matching works", features=_FEATURES,
        )
        return

    settings = get_settings()
    with st.spinner("Matching jobs with your CV…"):
        results = ranked_matches(st.session_state, cv, outcome, settings.scoring_weights)
    low = sum(r.confidence == "Low" for r in results)
    section_header(
        f"{len(results)} job{'s' if len(results) != 1 else ''} ranked for {cv.filename}",
        f"From your search for “{outcome.query.keywords}”. Matching runs on this computer; nothing is sent to "
        "external services.",
    )
    st.caption(MATCH_LIMITATIONS)
    if low:
        st.caption(f"{low} job(s) have too little information in their description for a reliable score; they are "
                   "listed after the others.")
    for i, result in enumerate(results):
        st.html(match_card_html(result))
        with st.expander(f"Score breakdown — {result.score}/100, {result.confidence.lower()} confidence",
                         icon=":material/analytics:"):
            render_breakdown(result)
        if i < len(results) - 1:
            st.write("")
