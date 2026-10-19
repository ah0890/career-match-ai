"""Job Matches — ranked, explainable opportunities."""

from __future__ import annotations

import streamlit as st

from config.settings import get_settings
from src.cv.session import get_active_cv
from src.matching.engine import MATCH_LIMITATIONS
from src.matching.recommendations import RECOMMENDATION_DISCLAIMER, Label, prioritise
from src.pages.find_jobs import OUTCOME_KEY
from src.services.matching import ranked_matches
from src.ui.components import Feature, Metric, metric_grid, notice, page_header, section_header
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
    ranked = prioritise(results, settings.thresholds)
    low = sum(m.result.confidence == "Low" for m in ranked)
    section_header(
        f"{len(ranked)} job{'s' if len(ranked) != 1 else ''} ranked for {cv.filename}",
        f"From your search for “{outcome.query.keywords}”. Matching runs on this computer; nothing is sent to "
        "external services.",
    )
    counts = {label: sum(m.recommendation.label is label for m in ranked) for label in Label}
    t = settings.thresholds
    metric_grid([
        Metric("Apply", str(counts[Label.APPLY]), f"Score {t.apply:g}+ with no essential gaps"),
        Metric("Apply after improvement", str(counts[Label.APPLY_AFTER_IMPROVEMENT]),
               f"Score {t.improve:g}+, or an essential requirement not shown"),
        Metric("Don't prioritize", str(counts[Label.DONT_PRIORITIZE]), f"Score below {t.improve:g}, or expired"),
    ])
    st.caption(f"{MATCH_LIMITATIONS} {RECOMMENDATION_DISCLAIMER}")
    if low:
        st.caption(f"{low} job(s) have too little information in their description for a reliable score; they are "
                   "listed after the others.")
    for i, m in enumerate(ranked):
        st.html(match_card_html(m.result, m.recommendation))
        with st.expander(f"Why {m.recommendation.label.value} — score {m.result.score}/100, "
                         f"{m.result.confidence.lower()} confidence", icon=":material/analytics:"):
            render_breakdown(m.result, m.recommendation)
        if i < len(ranked) - 1:
            st.write("")
