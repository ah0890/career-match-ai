"""Job Matches — ranked, explainable opportunities."""

from __future__ import annotations

import streamlit as st

from config.settings import get_settings
from src.cv.session import get_active_cv
from src.matching.engine import MATCH_LIMITATIONS
from src.jobs.models import WorkArrangement
from src.matching.browse import (COMPARE_LIMIT, SORT_LABELS, MatchFilter, filter_matches, page_slice, sort_matches,
                                 source_names)
from src.matching.recommendations import Label, RankedMatch, prioritise
from src.pages.company_intelligence import PREFILL_KEY as COMPANY_PREFILL_KEY
from src.pages.find_jobs import OUTCOME_KEY
from src.pages.interview_preparation import PREFILL_KEY as INTERVIEW_PREFILL_KEY
from src.pages.cv_studio import PREFILL_KEY as TAILOR_PREFILL_KEY
from src.matching.improvements import improvement_plan
from src.db.engine import session_scope
from src.services.matching import match_profile, ranked_matches
from src.tracker.repository import find_by_job, save_job
from src.ui.components import Feature, Metric, empty_state, metric_grid, notice, page_header, section_header
from src.ui.layouts import call_to_action, empty_page_body
from src.ui.navigation import go_to
from src.ui.match_cards import (comparison_html, description_html, match_card_html, render_breakdown,
                                render_improvement_plan)

_FEATURES = [
    Feature("Explainable scores", "Required skills, experience, responsibilities, education and "
            "keywords are scored separately using configurable weights."),
    Feature("Recommendations", "APPLY, APPLY AFTER IMPROVEMENT or DON'T PRIORITIZE — guidance for "
            "prioritising, not a prediction of being hired."),
    Feature("Mandatory requirements", "A clearly essential qualification that your CV does not "
            "evidence is flagged, even when the overall score is high."),
]
PER_PAGE = 15
_PAGE_KEY = "jm_page"
_ARRANGEMENTS = {"Remote": WorkArrangement.REMOTE, "Hybrid": WorkArrangement.HYBRID,
                 "On-site": WorkArrangement.ONSITE}


def _filters(ranked: list[RankedMatch]) -> tuple[MatchFilter, str]:
    with st.container(border=True):
        labels = st.pills("Recommendation", [label.value for label in Label], selection_mode="multi",
                          default=[label.value for label in Label], key="jm_labels") or []
        c2, c3 = st.columns(2)
        min_score = c2.slider("Minimum score", 0, 100, 0, step=5, key="jm_min_score")
        sort = c3.selectbox("Sort by", list(SORT_LABELS), format_func=SORT_LABELS.get, key="jm_sort")
        with st.expander("More filters"):
            m1, m2 = st.columns(2)
            sources = m1.multiselect("Sources", source_names(ranked), key="jm_sources", placeholder="All sources")
            arrangements = m2.multiselect("Work arrangement", list(_ARRANGEMENTS), key="jm_arrangements",
                                          placeholder="Any arrangement")
            k1, k2, k3 = st.columns(3)
            low = k1.checkbox("Include jobs with limited information", value=True, key="jm_low")
            hide_expired = k2.checkbox("Hide expired listings", value=True, key="jm_hide_expired")
            no_gaps = k3.checkbox("Only jobs with no essential gaps", value=False, key="jm_no_gaps")
    criteria = MatchFilter(
        labels=frozenset(Label(v) for v in labels), min_score=min_score, include_low_confidence=low,
        hide_expired=hide_expired, sources=frozenset(sources),
        arrangements=frozenset(_ARRANGEMENTS[a] for a in arrangements), essential_gaps_ok=not no_gaps,
    )
    return criteria, sort


def _compare(matches: list[RankedMatch]) -> None:
    by_key = {m.result.job.key: m for m in matches}
    with st.expander("Compare jobs side by side", icon=":material/compare_arrows:"):
        chosen = st.multiselect(
            f"Choose 2 or {COMPARE_LIMIT} jobs", list(by_key), max_selections=COMPARE_LIMIT, key="jm_compare",
            format_func=lambda k: f"{by_key[k].result.job.title} — {by_key[k].result.job.company or 'company not provided'}"
                                  f" ({by_key[k].result.score})",
            placeholder="Select jobs to compare",
        )
        chosen = [by_key[k] for k in chosen if k in by_key]
        if len(chosen) >= 2:
            st.html(comparison_html(chosen))
        else:
            st.caption("Select at least two jobs from the current results.")


def _pager(total_pages: int, position: str) -> None:
    if total_pages <= 1:
        return
    page = st.session_state.get(_PAGE_KEY, 1)
    c1, c2, c3 = st.columns([1, 2, 1])
    if c1.button("Previous", key=f"jm_prev_{position}", disabled=page <= 1, icon=":material/chevron_left:",
                 width="stretch"):
        st.session_state[_PAGE_KEY] = page - 1
        st.rerun()
    c2.markdown(f"<p style='text-align:center;margin:8px 0'>Page {page} of {total_pages}</p>", unsafe_allow_html=True)
    if c3.button("Next", key=f"jm_next_{position}", disabled=page >= total_pages, icon=":material/chevron_right:",
                 width="stretch"):
        st.session_state[_PAGE_KEY] = page + 1
        st.rerun()


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
               f"Score {t.improve:g}–{t.apply - 1:g}, or higher with an essential gap"),
        Metric("Don't prioritize", str(counts[Label.DONT_PRIORITIZE]), f"Score below {t.improve:g}, or expired"),
    ])
    st.caption(f"{MATCH_LIMITATIONS} Recommendations only help you decide where to spend your effort.")
    if low:
        st.caption(f"{low} job(s) have too little information in their description for a reliable score; they are "
                   "listed after the others.")

    criteria, sort = _filters(ranked)
    shown = sort_matches(filter_matches(ranked, criteria), sort)
    signature = (criteria.labels, criteria.min_score, criteria.include_low_confidence, criteria.hide_expired,
                 criteria.sources, criteria.arrangements, criteria.essential_gaps_ok, sort, len(ranked))
    if st.session_state.get("jm_signature") != signature:  # new filters start again from the first page
        st.session_state["jm_signature"] = signature
        st.session_state[_PAGE_KEY] = 1
    if not shown:
        empty_state("No jobs match these filters", "Lower the minimum score or include more recommendation types.")
        return
    _compare(shown)
    page_items, pages = page_slice(shown, st.session_state.get(_PAGE_KEY, 1), PER_PAGE)
    start = (min(st.session_state.get(_PAGE_KEY, 1), pages) - 1) * PER_PAGE
    st.caption(f"Showing {start + 1}–{start + len(page_items)} of {len(shown)} job(s)"
               + (f" ({len(ranked) - len(shown)} hidden by filters)." if len(shown) < len(ranked) else "."))
    with session_scope(settings.database_url) as s:
        saved = {m.result.job.key for m in page_items if find_by_job(s, m.result.job.key) is not None}
    for i, m in enumerate(page_items):
        with st.container(key=f"cm_job_{start + i}"):
            st.html(match_card_html(m.result, m.recommendation))
            with st.expander(f"Why {m.recommendation.label.value} — score {m.result.score}/100, "
                             f"{m.result.confidence.lower()} confidence", icon=":material/analytics:"):
                render_breakdown(m.result, m.recommendation)
            with st.expander("Improve your CV for this job", icon=":material/edit_note:"):
                render_improvement_plan(improvement_plan(match_profile(st.session_state, cv), m.result))
            with st.expander("Full job description", icon=":material/article:"):
                st.html(description_html(m.result.job))
            a0, a1, a2, a3 = st.columns(4)
            if a0.button("Tailor CV", icon=":material/edit_document:", key=f"jm_tailor_{start + i}", width="stretch"):
                st.session_state[TAILOR_PREFILL_KEY] = m.result.job
                go_to("cv-studio")
            if a1.button("Prepare for interview", icon=":material/school:", key=f"jm_prep_{start + i}", width="stretch"):
                st.session_state[INTERVIEW_PREFILL_KEY] = m.result.job.key
                go_to("interview-preparation")
            if m.result.job.company and a2.button("Research company", icon=":material/domain:",
                                                  key=f"jm_research_{start + i}", width="stretch"):
                st.session_state[COMPANY_PREFILL_KEY] = m.result.job.company
                go_to("company-intelligence")
            if m.result.job.key in saved:
                a3.button("Saved to tracker", icon=":material/check:", key=f"jm_saved_{start + i}", disabled=True,
                          width="stretch")
            elif a3.button("Save to tracker", icon=":material/bookmark_add:", key=f"jm_save_{start + i}", width="stretch"):
                with session_scope(settings.database_url) as s:
                    save_job(s, m, m.result.job)
                st.toast(f"Saved {m.result.job.title} to your tracker.", icon=":material/bookmark_added:")
                st.rerun()
    _pager(pages, "bottom")
