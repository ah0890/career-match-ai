"""Find Jobs — search configured job sources."""

from __future__ import annotations

import streamlit as st
from pydantic import ValidationError

from config.settings import get_settings
from src.jobs.countries import COUNTRIES
from src.jobs.models import EmploymentType, SearchQuery, WorkArrangement
from src.providers.registry import UNSUPPORTED_SOURCES, statuses
from src.services.job_search import SearchOutcome, search_jobs
from src.services.runtime import get_http
from src.ui.components import ListItem, empty_state, item_list, notice, page_header, section_header
from src.ui.job_cards import job_card_html, provider_result_badge

SEARCH_PREFILL_KEY = "cm_search_prefill"
OUTCOME_KEY = "fj_outcome"
_FORM_KEYS = ("fj_query", "fj_location", "fj_country", "fj_arrangement", "fj_level", "fj_type",
              "fj_posted", "fj_required", "fj_preferred", "fj_industry", "fj_salary")

WORK_ARRANGEMENTS = {"Any": WorkArrangement.ANY, "Remote": WorkArrangement.REMOTE,
                     "Hybrid": WorkArrangement.HYBRID, "On-site": WorkArrangement.ONSITE}
EXPERIENCE_LEVELS = ["Any", "Internship", "Entry level", "Mid level", "Senior", "Lead / Principal",
                     "Manager", "Director / Executive"]
EMPLOYMENT_TYPES = {"Any": EmploymentType.ANY, "Full-time": EmploymentType.FULL_TIME,
                    "Part-time": EmploymentType.PART_TIME, "Contract": EmploymentType.CONTRACT,
                    "Temporary": EmploymentType.TEMPORARY, "Internship": EmploymentType.INTERNSHIP}
COUNTRY_OPTIONS = {"Any country": None, **{name: code for code, name in sorted(COUNTRIES.items(), key=lambda kv: kv[1])}}
DATE_POSTED = {"Any time": None, "Past 24 hours": 1, "Past 3 days": 3, "Past week": 7, "Past month": 30}


def validate_search(query: str) -> list[str]:
    errors = []
    if not query.strip():
        errors.append("Enter a job title or keywords.")
    elif len(query.strip()) < 2:
        errors.append("Search keywords must be at least 2 characters.")
    elif len(query) > 200:
        errors.append("Search keywords must be 200 characters or fewer.")
    return errors


def _split(value: str | None) -> tuple[str, ...]:
    return tuple(s.strip() for s in (value or "").split(",") if s.strip())


def build_query(state) -> SearchQuery:
    level = state.get("fj_level", "Any")
    return SearchQuery(
        keywords=state.get("fj_query", ""),
        location=state.get("fj_location") or None,
        country=COUNTRY_OPTIONS[state.get("fj_country", "Any country")],
        work_arrangement=WORK_ARRANGEMENTS[state.get("fj_arrangement", "Any")],
        employment_type=EMPLOYMENT_TYPES[state.get("fj_type", "Any")],
        experience_level=None if level == "Any" else level,
        posted_within_days=DATE_POSTED[state.get("fj_posted", "Any time")],
        salary_min=int(state["fj_salary"]) if state.get("fj_salary") else None,
        required_skills=_split(state.get("fj_required")),
        preferred_skills=_split(state.get("fj_preferred")),
        industry=state.get("fj_industry") or None,
    )


def _apply_prefill() -> bool:
    prefill = st.session_state.pop(SEARCH_PREFILL_KEY, None)
    if prefill:
        st.session_state["fj_query"] = prefill.get("query", "")
        st.session_state["fj_location"] = prefill.get("location", "")
        return True
    return False


def _reset() -> None:
    for key in (*_FORM_KEYS, OUTCOME_KEY, "fj_errors"):
        st.session_state.pop(key, None)


def _run_search() -> None:
    errors = validate_search(st.session_state.get("fj_query", ""))
    if errors:
        st.session_state["fj_errors"] = errors
        st.session_state.pop(OUTCOME_KEY, None)
        return
    st.session_state.pop("fj_errors", None)
    try:
        query = build_query(st.session_state)
    except ValidationError:
        st.session_state["fj_errors"] = ["Some search values are invalid. Check the filters and try again."]
        return
    settings = get_settings()
    with st.spinner("Searching job sources…"):
        st.session_state[OUTCOME_KEY] = search_jobs(query, settings, get_http(settings))


_AVAILABILITY = {"ready": ("Available", "success"), "needs_configuration": ("Needs setup", "warning"),
                 "disabled": ("Disabled", "neutral"), "offline": ("Offline", "neutral")}


def _sources_panel() -> None:
    with st.expander("Job sources", icon=":material/hub:"):
        rows = []
        for s in statuses(get_settings()):
            label, tone = _AVAILABILITY[s.availability]
            info = s.provider.info
            rows.append(ListItem(info.name, f"{info.coverage} {s.detail}", label, tone,
                                 " · ".join(info.notes) or None))
        item_list(rows)
        st.caption("Not supported (no public job-search API, and automated scraping would breach their terms): "
                   + ", ".join(u.name for u in UNSUPPORTED_SOURCES) + ".")


_FILTER_LABELS = {"location": "location", "country": "country", "work_arrangement": "work arrangement",
                  "employment_type": "employment type", "posted_within_days": "date posted",
                  "salary_min": "minimum salary", "employer": "employer", "experience_level": "experience level",
                  "industry": "industry"}


def requested_filters(q: SearchQuery) -> list[str]:
    values = {"location": q.location, "country": q.country,
              "work_arrangement": q.work_arrangement is not WorkArrangement.ANY,
              "employment_type": q.employment_type is not EmploymentType.ANY,
              "posted_within_days": q.posted_within_days, "salary_min": q.salary_min, "employer": q.employer,
              "experience_level": q.experience_level, "industry": q.industry}
    return [k for k, v in values.items() if v]


def filters_not_applied(outcome: SearchOutcome) -> list[str]:
    """Per searched source, the requested filters it cannot apply (so nothing is silently ignored)."""
    from src.providers.registry import PROVIDER_CLASSES

    supported = {cls.info.id: cls.info.supported_filters for cls in PROVIDER_CLASSES}
    wanted = requested_filters(outcome.query)
    notes = []
    for r in outcome.succeeded:
        missing = [_FILTER_LABELS[f] for f in wanted if f not in supported.get(r.provider_id, frozenset())
                   and f != "work_arrangement"]  # remote-only boards already enforce arrangement by skipping
        if missing:
            notes.append(f"{r.provider_name} did not filter by {', '.join(missing)}")
    return notes


def _render_outcome(outcome: SearchOutcome) -> None:
    jobs = outcome.jobs
    ok = outcome.succeeded
    q = outcome.query
    section_header(
        f"{len(jobs)} job{'s' if len(jobs) != 1 else ''} found",
        f"Searched {len(ok)} of {len(outcome.results)} source(s) for “{q.keywords}”"
        + (f" in {q.location}" if q.location else "") + ".",
    )
    rows = []
    for r in outcome.results:
        label, tone = provider_result_badge(r)
        if r.status == "ok":
            detail = f"{len(r.jobs)} matching job(s)."
            if r.from_cache and r.fetched_at:
                detail += (f" Data retrieved {r.fetched_at.astimezone():%d %b, %H:%M} and reused to respect "
                           "the source's usage limits.")
        else:
            detail = r.message or ""
        rows.append(ListItem(r.provider_name, detail, label, tone))
    item_list(rows)

    if any(r.retryable for r in outcome.failed):
        if st.button("Retry failed sources", icon=":material/refresh:", key="fj_retry"):
            _run_search()
            st.rerun()

    if not ok:
        if not outcome.failed:
            notice("No job source could be searched with these settings. Adjust the filters or enable a source "
                   "in Settings.", tone="warning")
        return
    if not jobs:
        empty_state("No matching jobs", "No source returned jobs for this search. Try broader keywords, a "
                    "different location or fewer filters.")
        return
    notes = filters_not_applied(outcome)
    if notes:
        st.caption("Some sources cannot apply every filter: " + "; ".join(notes) + ".")
    for job in jobs:
        st.html(job_card_html(job))


def render() -> None:
    page_header(
        "Find Jobs",
        "Search the job sources you have configured. Results are always attributed to the source that returned them.",
        eyebrow="Discover",
    )
    prefilled = _apply_prefill()

    with st.container(border=True):
        with st.form("job_search", border=False):
            c1, c2, c0 = st.columns([3, 2, 2])
            c1.text_input("Job title or keywords", key="fj_query", placeholder="e.g. Data Analyst, Python, SQL")
            c2.text_input("Location", key="fj_location", placeholder="City or region")
            c0.selectbox("Country", list(COUNTRY_OPTIONS), key="fj_country")
            c3, c4, c5, c6 = st.columns(4)
            c3.selectbox("Work arrangement", list(WORK_ARRANGEMENTS), key="fj_arrangement")
            c4.selectbox("Experience level", EXPERIENCE_LEVELS, key="fj_level")
            c5.selectbox("Employment type", list(EMPLOYMENT_TYPES), key="fj_type")
            c6.selectbox("Date posted", list(DATE_POSTED), key="fj_posted")
            with st.expander("More filters"):
                m1, m2 = st.columns(2)
                m1.text_input("Required skills", key="fj_required", placeholder="Comma-separated")
                m2.text_input("Preferred skills", key="fj_preferred", placeholder="Comma-separated")
                m3, m4 = st.columns(2)
                m3.text_input("Industry", key="fj_industry", placeholder="e.g. Manufacturing")
                m4.number_input("Minimum salary (where the source supports it)", key="fj_salary",
                                min_value=0, step=1000, value=None, placeholder="No minimum")
            b1, b2, _ = st.columns([1, 1, 4])
            searched = b1.form_submit_button("Search", type="primary", icon=":material/search:", width="stretch")
            b2.form_submit_button("Reset", on_click=_reset, icon=":material/restart_alt:", width="stretch")
    _sources_panel()

    if searched or prefilled:
        _run_search()

    for e in st.session_state.get("fj_errors", []):
        st.error(e, icon=":material/error:")
    outcome = st.session_state.get(OUTCOME_KEY)
    if outcome is not None:
        _render_outcome(outcome)
