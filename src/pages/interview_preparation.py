"""Interview Preparation — prioritised questions for a chosen job."""

from __future__ import annotations

import re

import streamlit as st

from config.settings import get_settings
from src.cv.session import get_active_cv
from src.interview.prep import build_prep_plan, plan_markdown
from src.matching.recommendations import prioritise
from src.pages.find_jobs import OUTCOME_KEY
from src.services.matching import match_profile, ranked_matches
from src.ui.components import Feature, ListItem, item_list, notice, page_header, section_header
from src.ui.interview_view import question_card_html
from src.ui.layouts import empty_page_body

PREFILL_KEY = "ip_prefill"  # a job key set by Job Matches
_FEATURES = [
    Feature("Likely questions", "Technical, behavioural, role and motivation questions ranked Very likely to "
            "Possible, each with the job's own reason."),
    Feature("Your own material", "The lines of your CV each question can draw on — examples are never invented."),
    Feature("STAR guidance", "A structure for every answer, plus honest ways to handle requirements your CV does "
            "not show."),
]


def _empty(title: str, message: str, cta_label: str, target: str) -> None:
    empty_page_body(empty_title=title, empty_message=message, cta_label=cta_label, cta_target=target,
                    cta_key="ip_cta", features_title="What each plan includes", features=_FEATURES)


def render() -> None:
    page_header(
        "Interview Preparation",
        "Prepare for each role with prioritised questions based on the job description and your CV.",
        eyebrow="Prepare",
    )
    cv = get_active_cv(st.session_state)
    outcome = st.session_state.get(OUTCOME_KEY)
    if cv is None or cv.extraction.needs_ocr or not cv.extraction.text.strip():
        _empty("Upload your CV first", "Preparation plans link each question to your own experience, so a readable "
               "CV is needed.", "Upload CV", "cv-analysis")
        return
    if outcome is None or not outcome.unique_jobs:
        _empty("No jobs to prepare for yet", "Search for jobs, then choose one here or use “Prepare for interview” on "
               "Job Matches.", "Find jobs", "find-jobs")
        return

    settings = get_settings()
    ranked = prioritise(ranked_matches(st.session_state, cv, outcome, settings.scoring_weights), settings.thresholds)
    by_key = {m.result.job.key: m for m in ranked}
    prefill = st.session_state.pop(PREFILL_KEY, None)
    if prefill in by_key:
        st.session_state["ip_job"] = prefill
    if st.session_state.get("ip_job") not in by_key:
        st.session_state["ip_job"] = ranked[0].result.job.key
    with st.container(border=True):
        key = st.selectbox(
            "Job", list(by_key), key="ip_job",
            format_func=lambda k: f"{by_key[k].result.job.title} — {by_key[k].result.job.company or 'company not provided'}"
                                  f" · {by_key[k].recommendation.label.value} ({by_key[k].result.score})")
    match = by_key[key]
    plan = build_prep_plan(match_profile(st.session_state, cv), match.result, st.session_state.get("ci_profile"))

    notice(plan.disclaimer, tone="info")
    for n in plan.notes:
        st.caption(n)
    kinds = list(dict.fromkeys(q.kind for q in plan.questions))
    section_header(f"{len(plan.questions)} questions to prepare",
                   "Ordered by how likely they are, based on what the job description emphasises.")
    c1, c2 = st.columns([3, 1])
    shown = c1.pills("Question type", kinds, selection_mode="multi", default=kinds, key="ip_kinds") or []
    slug = re.sub(r"[^a-z0-9]+", "-", f"{plan.job_title} {plan.company or ''}".lower()).strip("-")[:60]
    c2.download_button("Download plan", plan_markdown(plan), file_name=f"interview-prep-{slug}.md",
                       mime="text/markdown", icon=":material/download:", width="stretch")
    for q in plan.questions:
        if q.kind in shown:
            st.html(question_card_html(q))

    section_header("Questions to ask the interviewer")
    item_list(ListItem(q) for q in plan.questions_to_ask)
    section_header("Before the interview")
    item_list(ListItem(c, badge="To do", tone="neutral") for c in plan.checklist)
