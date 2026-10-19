"""Dashboard — overview of the job search, built only from real activity."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from config.settings import get_settings
from src.analytics.dashboard import activity_summary, match_summary, pipeline
from src.cv.session import get_active_cv
from src.db.engine import session_scope
from src.matching.recommendations import Label, prioritise
from src.pages.find_jobs import OUTCOME_KEY, SEARCH_PREFILL_KEY
from src.services.matching import ranked_matches
from src.tracker.recruitment import tracking_summary
from src.tracker.repository import due_actions, list_applications
from src.ui.charts import pipeline_figure, score_figure, weekly_figure
from src.ui.components import (
    ListItem, Metric, Step, empty_state, item_list, metric_grid, page_header, section_header, steps,
)
from src.ui.navigation import go_to
from src.ui.tracker_view import follow_up_label

_CHART_CONFIG = {"displayModeBar": False, "responsive": True}


_HERO_POINTS = ("Transparent, explainable scores", "Permitted job sources only", "Your data stays on this computer")


def _hero() -> None:
    """Welcome band with the quick search: the first thing a returning user needs."""
    with st.container(key="cm_hero"):
        page_header(
            "Welcome to CareerMatch AI",
            "Upload your CV, discover relevant vacancies and see — with evidence — how well each one fits.",
            eyebrow="Dashboard",
        )
        with st.form("dashboard_quick_search", border=False):
            c1, c2, c3 = st.columns([5, 3, 2], vertical_alignment="bottom")
            query = c1.text_input("Job title or keywords", placeholder="e.g. Quality Engineer")
            location = c2.text_input("Location", placeholder="City, country or Remote")
            submitted = c3.form_submit_button(
                "Search jobs", type="primary", icon=":material/search:", width="stretch"
            )
        st.html('<ul class="cm-hero-points">' + "".join(f"<li>{p}</li>" for p in _HERO_POINTS) + "</ul>")
        if submitted:
            if not query.strip():
                st.error("Enter a job title or keywords to search.")
            else:
                st.session_state[SEARCH_PREFILL_KEY] = {"query": query.strip(), "location": location.strip()}
                go_to("find-jobs")


def _chart(fig, table: pd.DataFrame, key: str) -> None:
    with st.container(key=f"cm_chart_{key}"):
        st.plotly_chart(fig, config=_CHART_CONFIG, key=key, width="stretch")
        with st.expander("View as table"):
            st.dataframe(table, hide_index=True, width="stretch")


def render() -> None:
    _hero()

    settings = get_settings()
    cv = get_active_cv(st.session_state)
    cv_usable = cv is not None and not cv.extraction.needs_ocr and bool(cv.extraction.text.strip())
    outcome = st.session_state.get(OUTCOME_KEY)
    with session_scope(settings.database_url) as s:
        activity = activity_summary(s)
        due = due_actions(s)
        tracking = tracking_summary(list_applications(s), no_response_days=settings.tracker_no_response_days)
    matches = None
    if cv_usable and outcome is not None and outcome.unique_jobs:
        matches = match_summary(prioritise(ranked_matches(st.session_state, cv, outcome, settings.scoring_weights),
                                           settings.thresholds))

    section_header("Getting started", "Complete these steps to unlock matching, research and tracking.")
    steps([
        Step("Upload your CV", "Add a PDF or DOCX CV. It stays on this computer.", done=cv is not None),
        Step("Review your CV analysis", "See structure, ATS compatibility and prioritised improvements.",
             done=cv_usable),
        Step("Search for jobs", "Query the job sources you have configured in Settings.",
             done=outcome is not None or activity.searches_30d > 0),
        Step("Review ranked matches", "Inspect evidence, missing requirements and recommendations.",
             done=matches is not None),
        Step("Prepare and track", "Research employers, prepare for interviews and track applications.",
             done=activity.tracked > 0),
    ])

    section_header("Your activity")
    if not activity.has_activity and matches is None:
        empty_state(
            "No activity yet",
            "Metrics such as jobs analysed, strong matches, applications and interviews appear here once "
            "you have searched for and saved jobs. Nothing is shown until it is based on your real data.",
        )
        return

    metric_grid([
        Metric("Searches", str(activity.searches_30d), "In the last 30 days"),
        Metric("Strong matches", str(matches.by_label[Label.APPLY]) if matches else "—",
               f"APPLY among {matches.total} job(s) in your latest results" if matches
               else "Upload a CV and search to see matches"),
        Metric("Active applications", str(tracking.active), "Applied, not rejected or withdrawn"),
        Metric("Interviews and offers", f"{tracking.interviews_received} · {tracking.offers}",
               "Applications with an interview · with an offer"),
    ])

    if due:
        section_header("Follow-ups due", "Active applications with a follow-up in the next week or overdue.")
        item_list(ListItem(a.title, a.next_action or "Follow up", follow_up_label(a)[0], follow_up_label(a)[1],
                           a.company) for a in due[:5])

    if matches and matches.top:
        section_header("Top matches in your latest results")
        item_list(ListItem(m.result.job.title, m.recommendation.headline, m.recommendation.label.value,
                           m.recommendation.tone,
                           f"{m.result.job.company or 'Company not provided'} · score {m.result.score}/100")
                  for m in matches.top)
        if st.button("Open Job Matches", key="db_open_matches", icon=":material/arrow_forward:"):
            go_to("job-matches")

    charts = []
    if activity.tracked:
        rows = pipeline(activity.status_counts)
        charts.append((pipeline_figure(rows), pd.DataFrame(rows, columns=["Status", "Applications"]), "db_pipeline"))
        if any(w.count for w in activity.applied_per_week):
            charts.append((weekly_figure(activity.applied_per_week),
                           pd.DataFrame([(f"{w.week_start:%d %b %Y}", w.count) for w in activity.applied_per_week],
                                        columns=["Week starting", "Applications submitted"]), "db_weekly"))
    if matches and len(matches.scores) >= 3:
        t = settings.thresholds
        charts.append((score_figure(matches.scores, t.improve, t.apply),
                       pd.DataFrame(sorted(matches.scores, reverse=True), columns=["Match score"]), "db_scores"))
    if charts:
        section_header("Trends", "Based only on your own searches and tracked applications.")
        for i in range(0, len(charts), 2):
            cols = st.columns(2)
            for col, (fig, table, key) in zip(cols, charts[i:i + 2]):
                with col:
                    _chart(fig, table, key)
        if matches and matches.total > len(matches.scores):
            st.caption(f"{matches.total - len(matches.scores)} job(s) with too little information for a reliable score "
                       "are left out of the score chart.")
