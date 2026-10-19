"""CV Versions — keep tailored CVs for different career paths, compare them and choose which one to use."""

from __future__ import annotations

from html import escape

import pandas as pd
import streamlit as st

from config.settings import get_settings
from src.cv.session import get_active_cv, set_active_cv
from src.cv.versions import (
    MAX_VERSIONS, STORAGE_NOTICE, VersionError, as_active_cv, compare_versions, delete_all, delete_version,
    extraction_of, find_by_sha, list_versions, rename_version, save_version,
)
from src.db.engine import session_scope
from src.matching.engine import build_profile, rank_jobs
from src.pages.find_jobs import OUTCOME_KEY
from src.ui.components import (
    Feature, Metric, badge_html, empty_state, feature_grid, metric_grid, notice, page_header, section_header,
)
from src.ui.layouts import call_to_action
from src.ui.score_components import chips_html

_FLASH = "cvv_flash"
_COMPARE_JOBS = 20


def _db() -> str:
    return get_settings().database_url


def _save_form(cv) -> None:
    with st.container(border=True):
        st.markdown(f"**Save your active CV as a version** — {cv.filename}")
        with st.form("cvv_save", border=False, clear_on_submit=True):
            c1, c2 = st.columns([1, 2])
            name = c1.text_input("Version name", max_chars=120, placeholder="e.g. Quality management")
            purpose = c2.text_input("What it is for (optional)", max_chars=300,
                                    placeholder="e.g. Senior quality roles in manufacturing")
            consent = st.checkbox("I want to keep this CV's text on this computer")
            st.caption(STORAGE_NOTICE)
            if st.form_submit_button("Save version", type="primary", icon=":material/save:"):
                if not consent:
                    st.error("Tick the box to confirm you want this CV's text kept on this computer.",
                             icon=":material/error:")
                    return
                try:
                    with session_scope(_db()) as s:
                        save_version(s, cv, name, purpose)
                    st.session_state[_FLASH] = f"Saved “{name.strip()}”."
                    st.rerun()
                except VersionError as exc:
                    st.error(str(exc), icon=":material/error:")


def _version_row(v, active_sha: str | None) -> None:
    badges = [badge_html("Active CV", "success")] if v.sha256 == active_sha else []
    if v.ats_score is not None:
        badges.append(badge_html(f"ATS {v.ats_score}/100 when saved", "neutral"))
    purpose = f"<p>{escape(v.purpose)}</p>" if v.purpose else ""
    st.html(
        f'<article class="cm-card cm-job"><div class="cm-job-head"><h3>{escape(v.name)}</h3>'
        f'<span class="cm-job-posted">Saved {v.created_at:%d %b %Y}</span></div>'
        f'<div class="cm-job-meta">{escape(v.filename)} · {len(v.text.split()):,} words</div>{purpose}'
        f'<div class="cm-badge-row">{"".join(badges)}</div></article>'
    )
    c1, c2, c3 = st.columns([1, 1, 2])
    if c1.button("Use as active CV", key=f"cvv_use_{v.id}", icon=":material/check_circle:",
                 disabled=v.sha256 == active_sha, width="stretch"):
        set_active_cv(st.session_state, as_active_cv(v))
        st.session_state.pop("cv_job_result", None)
        st.session_state[_FLASH] = f"“{v.name}” is now your active CV."
        st.rerun()
    confirm = f"cvv_confirm_{v.id}"
    if not st.session_state.get(confirm):
        if c2.button("Delete", key=f"cvv_delete_{v.id}", icon=":material/delete:", width="stretch"):
            st.session_state[confirm] = True
            st.rerun()
    else:
        with c3:
            st.warning(f"Delete “{v.name}” from this computer? This cannot be undone.", icon=":material/warning:")
            y, n = st.columns(2)
            if y.button("Yes, delete", type="primary", key=f"cvv_delete_yes_{v.id}", width="stretch"):
                with session_scope(_db()) as s:
                    delete_version(s, v.id)
                st.session_state.pop(confirm, None)
                st.session_state[_FLASH] = f"Deleted “{v.name}”."
                st.rerun()
            if n.button("Cancel", key=f"cvv_delete_no_{v.id}", width="stretch"):
                st.session_state.pop(confirm, None)
                st.rerun()
    with st.expander("Rename or describe"):
        with st.form(f"cvv_rename_{v.id}", border=False):
            r1, r2 = st.columns([1, 2])
            new_name = r1.text_input("Version name", value=v.name, max_chars=120)
            new_purpose = r2.text_input("What it is for", value=v.purpose or "", max_chars=300)
            if st.form_submit_button("Save changes"):
                try:
                    with session_scope(_db()) as s:
                        rename_version(s, v.id, new_name, new_purpose)
                    st.session_state[_FLASH] = "Version updated."
                    st.rerun()
                except VersionError as exc:
                    st.error(str(exc), icon=":material/error:")


def _compare(versions) -> None:
    section_header("Compare two versions", "How the second version differs from the first.")
    by_id = {v.id: v for v in versions}
    c1, c2 = st.columns(2)
    a = c1.selectbox("First version", list(by_id), format_func=lambda i: by_id[i].name, key="cvv_a")
    b = c2.selectbox("Second version", list(by_id), index=1, format_func=lambda i: by_id[i].name, key="cvv_b")
    if a == b:
        st.caption("Choose two different versions.")
        return
    cmp = compare_versions(by_id[a], by_id[b])
    delta = cmp.ats_after - cmp.ats_before
    metric_grid([
        Metric("ATS compatibility", f"{cmp.ats_before} → {cmp.ats_after}",
               f"{delta:+d} points" if delta else "No change"),
        Metric("Words", f"{cmp.words_before:,} → {cmp.words_after:,}", f"{cmp.words_after - cmp.words_before:+,d}"),
        Metric("Skills recognised", f"+{len(cmp.skills_added)} / −{len(cmp.skills_removed)}", "Added / removed"),
    ])
    st.dataframe(pd.DataFrame([(c.label, c.before, c.after, c.after - c.before, c.max_points) for c in cmp.components],
                              columns=["ATS component", "First", "Second", "Change", "Out of"]),
                 hide_index=True, width="stretch")
    s1, s2 = st.columns(2)
    with s1:
        st.markdown("**Skills only in the second version**")
        st.html(chips_html(cmp.skills_added, "success", "None"))
    with s2:
        st.markdown("**Skills only in the first version**")
        st.html(chips_html(cmp.skills_removed, "warning", "None"))
    if cmp.sections_added or cmp.sections_removed:
        st.caption("Sections added: " + (", ".join(cmp.sections_added) or "none") + " · Sections removed: "
                   + (", ".join(cmp.sections_removed) or "none"))
    with st.expander("Line-by-line differences"):
        if cmp.diff:
            st.code("\n".join(cmp.diff), language="diff", wrap_lines=True, height=420)
        else:
            st.caption("The text of the two versions is identical.")


def _against_results(versions) -> None:
    outcome = st.session_state.get(OUTCOME_KEY)
    if outcome is None or not outcome.unique_jobs:
        return
    section_header("Which version fits your latest results?",
                   f"Scores each version against up to {_COMPARE_JOBS} jobs from your search for "
                   f"“{outcome.query.keywords}”, using the same matching rules.")
    if not st.button("Compare versions against these jobs", key="cvv_vs_jobs", icon=":material/compare_arrows:"):
        return
    jobs = list(outcome.unique_jobs)[:_COMPARE_JOBS]
    weights = get_settings().scoring_weights
    per_version = {}
    with st.spinner("Matching each version…"):
        for v in versions:
            results = rank_jobs(build_profile(extraction_of(v)), jobs, weights)
            per_version[v.name] = {r.job.key: r.score for r in results if r.confidence != "Low"}
    keys = [j.key for j in jobs if all(j.key in scores for scores in per_version.values())]
    if not keys:
        st.caption("These jobs have too little information for a reliable comparison.")
        return
    best = {name: 0 for name in per_version}
    for k in keys:
        top = max(per_version, key=lambda n: per_version[n][k])
        best[top] += 1
    rows = [(name, round(sum(scores[k] for k in keys) / len(keys)), best[name]) for name, scores in per_version.items()]
    st.dataframe(pd.DataFrame(sorted(rows, key=lambda r: -r[1]),
                              columns=["Version", "Average match score", "Best fit for (jobs)"]),
                 hide_index=True, width="stretch")
    st.caption(f"Based on {len(keys)} job(s) with enough information. Scores estimate how well each version "
               "evidences the jobs' stated requirements; they do not predict hiring decisions.")


def render() -> None:
    page_header(
        "CV Versions",
        "Keep tailored CVs for different career paths and choose which one to match against.",
        eyebrow="Track",
    )
    if msg := st.session_state.pop(_FLASH, None):
        st.toast(msg, icon=":material/check_circle:")
    cv = get_active_cv(st.session_state)
    with session_scope(_db()) as s:
        versions = list_versions(s)
        saved_active = find_by_sha(s, cv.sha256) if cv else None

    if cv is not None and saved_active is None and not cv.extraction.needs_ocr and cv.extraction.text.strip():
        _save_form(cv)
    elif saved_active is not None:
        notice(f"Your active CV is saved as “{saved_active.name}”.", tone="success")

    if not versions:
        empty_state("No CV versions yet", "Upload a CV on the CV Analysis page, then save it here. Versions are only "
                    "kept when you choose to save them, and your original file is never stored.")
        if cv is None:
            _, mid, _ = st.columns([2, 1, 2])
            with mid:
                call_to_action("Go to CV Analysis", "cv-analysis", key="cvv_cta", icon=":material/arrow_forward:",
                               stretch=True)
        section_header("What you can do")
        feature_grid([
            Feature("Organise by career path", "Name and describe versions such as Technical, Management or "
                    "Quality Assurance."),
            Feature("Compare versions", "See ATS differences, skills added or removed, and line-by-line changes."),
            Feature("Find the best fit", "Score every version against your latest search results."),
        ])
        return

    section_header(f"{len(versions)} saved version{'s' if len(versions) != 1 else ''}",
                   f"Kept on this computer (up to {MAX_VERSIONS}).")
    for v in versions:
        _version_row(v, cv.sha256 if cv else None)
    if len(versions) >= 2:
        _compare(versions)
    _against_results(versions)

    with st.expander("Delete all saved versions"):
        st.caption("Removes every saved CV version from this computer. Your active CV in this session is not affected.")
        if st.checkbox("I understand this cannot be undone", key="cvv_all_ok") and st.button(
                "Delete all versions", type="primary", key="cvv_delete_all", icon=":material/delete_forever:"):
            with session_scope(_db()) as s:
                n = delete_all(s)
            st.session_state[_FLASH] = f"Deleted {n} version(s)."
            st.rerun()
