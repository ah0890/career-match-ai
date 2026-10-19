"""Company Intelligence — sourced employer research."""

from __future__ import annotations

import streamlit as st

from config.settings import get_settings
from src.company.models import CompanyCandidate, CompanyProfile
from src.company.relevance import companies_in, relevance
from src.company.wikimedia import find_companies, get_company, looks_like_organisation
from src.cv.session import get_active_cv
from src.matching.recommendations import prioritise
from src.pages.find_jobs import OUTCOME_KEY
from src.providers.base import ProviderError
from src.services.matching import ranked_matches
from src.services.runtime import get_http
from src.ui.components import Feature, ListItem, empty_state, feature_grid, item_list, notice, page_header, section_header
from src.ui.company_view import facts_html, profile_header_html, sources_html, summary_html

PREFILL_KEY = "ci_prefill"
_CANDIDATES = "ci_candidates"
_PROFILE = "ci_profile"
_ERROR = "ci_error"
_TYPED = "Type a company name"


def _search(name: str) -> None:
    st.session_state.pop(_PROFILE, None)
    st.session_state.pop(_ERROR, None)
    settings = get_settings()
    try:
        with st.spinner("Searching Wikidata…"):
            found, searched = find_companies(name, get_http(settings))
            st.session_state[_CANDIDATES] = (searched, found, searched != " ".join(name.split()))
    except ProviderError as exc:
        st.session_state[_ERROR] = exc.message
        st.session_state.pop(_CANDIDATES, None)


def _load(candidate: CompanyCandidate) -> None:
    st.session_state.pop(_ERROR, None)
    try:
        with st.spinner(f"Loading {candidate.label}…"):
            st.session_state[_PROFILE] = get_company(candidate.entity_id, get_http(get_settings()))
    except ProviderError as exc:
        st.session_state[_ERROR] = exc.message


def _search_form() -> None:
    outcome = st.session_state.get(OUTCOME_KEY)
    from_results = companies_in(list(outcome.unique_jobs)) if outcome is not None else []
    prefill = st.session_state.pop(PREFILL_KEY, None)
    if prefill:
        st.session_state["ci_name"] = prefill
        st.session_state["ci_pick"] = prefill if prefill in from_results else _TYPED
    with st.container(border=True):
        with st.form("ci_search", border=False):
            if from_results:
                st.selectbox("Company from your search results", [_TYPED, *from_results], key="ci_pick")
            st.text_input("Company name" if not from_results else "Or type a company name", key="ci_name",
                          placeholder="e.g. Siemens", max_chars=120)
            go = st.form_submit_button("Find company", type="primary", icon=":material/search:")
        st.caption("Company facts come from Wikidata and summaries from Wikipedia — public sources that link back to "
                   "their references. Only the company name is sent; your CV never leaves this computer.")
    pick = st.session_state.get("ci_pick", _TYPED)
    name = (st.session_state.get("ci_name") or "").strip()
    chosen = pick if from_results and pick != _TYPED else name
    if go or prefill:
        if len(chosen) < 2:
            st.session_state[_ERROR] = "Enter a company name of at least 2 characters."
        else:
            _search(chosen)


def _candidates() -> None:
    entry = st.session_state.get(_CANDIDATES)
    if entry is None or st.session_state.get(_PROFILE) is not None:
        return
    name, candidates, shortened = entry
    if shortened:
        st.caption(f"No entry matched the full name, so “{name}” was searched instead.")
    if not candidates:
        empty_state("No matching company found", f"Wikidata has no entry matching “{name}”. Smaller or private "
                    "employers often are not listed; check the company's own website and the job listing instead.")
        return
    section_header("Which company do you mean?",
                   "Several entries can share a name. Choose the one that matches the employer — nothing is assumed.")
    labels = {c.entity_id: f"{c.label} — {c.description or 'no description'}"
                           + ("" if looks_like_organisation(c) else " (may not be an organisation)") for c in candidates}
    choice = st.radio("Matching entries", list(labels), format_func=labels.get, key="ci_choice",
                      label_visibility="collapsed")
    if st.button("Show company profile", type="primary", key="ci_load", icon=":material/domain:"):
        _load(next(c for c in candidates if c.entity_id == choice))
        st.rerun()


def _relevance(profile: CompanyProfile) -> None:
    section_header("Relevance to your search", "Analysis connecting this company to your results and CV — not "
                   "sourced fact.")
    outcome = st.session_state.get(OUTCOME_KEY)
    cv = get_active_cv(st.session_state)
    if outcome is None:
        st.caption("Search for jobs to see roles at this company here.")
        return
    matches = []
    if cv is not None and cv.extraction.text.strip() and not cv.extraction.needs_ocr:
        settings = get_settings()
        matches = prioritise(ranked_matches(st.session_state, cv, outcome, settings.scoring_weights), settings.thresholds)
    rel = relevance(profile, list(outcome.unique_jobs), matches, cv.extraction.text if cv else None)
    if not rel.roles:
        st.caption(f"Your latest search has no roles listed by {profile.name}. Employer names are compared after "
                   "removing suffixes such as Ltd or AG, so differently named subsidiaries may not appear.")
    elif rel.matches:
        item_list(ListItem(m.result.job.title, m.recommendation.headline, m.recommendation.label.value,
                           m.recommendation.tone, f"Match score {m.result.score}/100 · {m.result.job.source_name}")
                  for m in rel.matches)
    else:
        item_list(ListItem(j.title, j.location, "Role", "neutral", j.source_name) for j in rel.roles)
        st.caption("Upload a CV to see how well you match these roles.")
    if rel.cv_mentions:
        st.caption("Your CV also mentions this company's listed industry or products: " + ", ".join(rel.cv_mentions)
                   + ". Consider drawing on that experience in your application.")


def _profile(profile: CompanyProfile) -> None:
    st.html(profile_header_html(profile))
    st.html(summary_html(profile.summary))
    section_header("Key facts", "Values as stated by the source, with the date the source gives where available.")
    st.html(facts_html(profile.facts, "No key facts are recorded for this company."))
    if profile.not_available:
        st.caption("Not available from these sources: " + ", ".join(profile.not_available) + ".")
    section_header("Leadership", "Current leaders as recorded by the source. Leadership changes often — verify "
                   "on the company's website.")
    st.html(facts_html(profile.leadership, "No current leadership is recorded for this company."))
    for n in profile.notes:
        notice(n, tone="info")
    _relevance(profile)
    with st.expander("Sources", icon=":material/link:"):
        st.html(sources_html(profile))
    if st.button("Research another company", key="ci_reset", icon=":material/restart_alt:"):
        for key in (_PROFILE, _CANDIDATES, _ERROR, "ci_choice"):
            st.session_state.pop(key, None)
        st.rerun()


def render() -> None:
    page_header(
        "Company Intelligence",
        "Research employers using credible public sources. Every important fact links to where it came from.",
        eyebrow="Prepare",
    )
    profile = st.session_state.get(_PROFILE)
    if profile is None:
        _search_form()
    if err := st.session_state.get(_ERROR):
        st.error(err, icon=":material/error:")
    if profile is not None:
        _profile(profile)
        return
    _candidates()
    if st.session_state.get(_CANDIDATES) is None and not st.session_state.get(_ERROR):
        section_header("What each company profile covers")
        feature_grid([
            Feature("Overview", "A short summary from Wikipedia, with attribution and a link to the article."),
            Feature("Key facts", "Industry, founding date, headquarters, size and ownership from Wikidata — each "
                    "with its source and date."),
            Feature("Leadership", "Current leaders as recorded publicly, or a clear note when none are recorded."),
            Feature("Relevance to your search", "Roles at this company in your results and how well you match "
                    "them — labelled as analysis, not fact."),
        ])
