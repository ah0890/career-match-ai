"""Tailor CV — adapt your CV to one job, edit by edit, then download it or save it as a version."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone

import streamlit as st

from config.settings import get_settings
from src.cv.extraction import ExtractionResult
from src.cv.session import ActiveCV, get_active_cv
from src.cv.versions import STORAGE_NOTICE, VersionError, save_version
from src.db.engine import session_scope
from src.jobs.models import safe_url
from src.matching.engine import build_profile, match_job
from src.matching.recommendations import prioritise
from src.pages.find_jobs import OUTCOME_KEY
from src.services.matching import ranked_matches
from src.tailoring.edits import apply_edits, suggest_edits
from src.tailoring.export import to_docx, to_pdf
from src.tracker.repository import find_by_job, save_job, set_status
from src.ui.components import Feature, Metric, metric_grid, notice, page_header, section_header
from src.ui.layouts import empty_page_body

PREFILL_KEY = "tl_prefill"  # a job key set by Job Matches
_FEATURES = [
    Feature("Edit by edit", "Every suggested change is previewed before and after; accept only what you want."),
    Feature("Nothing invented", "Edits reorder and emphasise what your CV already says. Adding a skill needs your "
            "confirmation that you genuinely have it."),
    Feature("Ready to send", "Download as DOCX or PDF, save as a CV version, and open the application."),
]


def _empty(title: str, message: str, cta: str, target: str) -> None:
    empty_page_body(empty_title=title, empty_message=message, cta_label=cta, cta_target=target, cta_key="tl_cta",
                    features_title="How tailoring works", features=_FEATURES)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "cv"


def _apply_section(match, job_key: str) -> None:
    job = match.result.job
    section_header("Apply", "Opening the listing never marks a job as applied — confirm it yourself afterwards.")
    url = safe_url(job.apply_url) or safe_url(job.listing_url)
    c1, c2 = st.columns(2)
    if url:
        c1.link_button("Apply on employer site" if job.apply_url else f"Open listing on {job.source_name}", url,
                       icon=":material/open_in_new:", type="primary", width="stretch")
    else:
        c1.caption("The source provided no valid link for this job.")
    db = get_settings().database_url
    with session_scope(db) as s:
        tracked = find_by_job(s, job_key)
        applied = tracked is not None and tracked.status in ("Applied", "Interview", "Offer")
    if applied:
        c2.button("Marked as applied", disabled=True, icon=":material/check:", key="tl_applied_done", width="stretch")
    elif c2.button("I submitted my application", key="tl_applied", icon=":material/task_alt:", width="stretch"):
        with session_scope(db) as s:
            app, _ = save_job(s, match, job)
            set_status(s, app.id, "Applied")
        st.toast("Saved to your tracker as Applied.", icon=":material/check_circle:")
        st.rerun()


def render() -> None:
    page_header(
        "Tailor CV",
        "Adapt your CV to a specific job — every change previewed, nothing invented.",
        eyebrow="Prepare",
    )
    cv = get_active_cv(st.session_state)
    outcome = st.session_state.get(OUTCOME_KEY)
    if cv is None or cv.extraction.needs_ocr or not cv.extraction.text.strip():
        _empty("Upload your CV first", "Tailoring starts from your own CV text.", "Upload CV", "cv-analysis")
        return
    if outcome is None or not outcome.unique_jobs:
        _empty("Choose a job to tailor for", "Search for jobs, then choose one here or use “Tailor CV” on Job Matches.",
               "Find jobs", "find-jobs")
        return

    settings = get_settings()
    ranked = prioritise(ranked_matches(st.session_state, cv, outcome, settings.scoring_weights), settings.thresholds)
    by_key = {m.result.job.key: m for m in ranked}
    prefill = st.session_state.pop(PREFILL_KEY, None)
    if prefill in by_key:
        st.session_state["tl_job"] = prefill
    if st.session_state.get("tl_job") not in by_key:
        st.session_state["tl_job"] = ranked[0].result.job.key
    with st.container(border=True):
        key = st.selectbox("Job", list(by_key), key="tl_job",
                           format_func=lambda k: f"{by_key[k].result.job.title} — "
                                                 f"{by_key[k].result.job.company or 'company not provided'} ({by_key[k].result.score})")
    match = by_key[key]
    job = match.result.job
    edits = suggest_edits(cv.extraction.text, match.result)

    section_header("Suggested changes", "Tick the changes you want. Nothing is applied until you accept it.")
    accepted: set[str] = set()
    if not edits:
        notice("No tailoring changes were found for this job: your CV already leads with what it asks for.",
               tone="success")
    for e in edits:
        with st.container(border=True):
            label = (f"I genuinely have {e.after} — add it" if e.needs_confirmation else f"Accept: {e.title}")
            if st.checkbox(label, value=e.default_on, key=f"tl_{key}_{e.id}"):
                accepted.add(e.id)
            st.caption(e.why)
            if not e.needs_confirmation:
                b, a = st.columns(2)
                b.markdown("**Before**")
                b.code(e.before or "(none)", language=None, wrap_lines=True)
                a.markdown("**After**")
                a.code(e.after, language=None, wrap_lines=True)

    tailored = apply_edits(cv.extraction.text, edits, accepted)
    text_key = f"tl_text_{hashlib.sha256((key + '|' + ','.join(sorted(accepted))).encode()).hexdigest()[:16]}"
    section_header("Your tailored CV", "Review and edit the text before downloading. Only keep what is true.")
    final = st.text_area("Tailored CV text", value=tailored, height=420, key=text_key, label_visibility="collapsed")

    after = match_job(build_profile(ExtractionResult(final, cv.extraction.kind, cv.extraction.page_count)), job,
                      settings.scoring_weights)
    delta = after.score - match.result.score
    metric_grid([
        Metric("Match score now", f"{match.result.score}", "Your current CV"),
        Metric("After tailoring", f"{after.score}", f"{delta:+d} points" if delta else "No change"),
        Metric("Changes accepted", f"{len(accepted)} of {len(edits)}"),
    ])
    st.caption("The score changes only because the CV now states or orders things differently. Recruiters judge "
               "the substance, so only keep what genuinely reflects your experience.")

    name = f"{job.title} — {job.company}" if job.company else job.title
    slug = _slug(f"cv {job.title} {job.company or ''}")
    d1, d2 = st.columns(2)
    d1.download_button("Download DOCX", to_docx(final), file_name=f"{slug}.docx", icon=":material/description:",
                       type="primary",
                       mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document", width="stretch")
    d2.download_button("Download PDF", to_pdf(final), file_name=f"{slug}.pdf", mime="application/pdf",
                       icon=":material/picture_as_pdf:", width="stretch")

    with st.expander("Save as a CV version", icon=":material/save:"):
        with st.form(f"tl_save_{key}", border=False):
            version_name = st.text_input("Version name", value=name[:120], max_chars=120)
            consent = st.checkbox("I want to keep this tailored CV's text on this computer")
            st.caption(STORAGE_NOTICE)
            if st.form_submit_button("Save version", type="primary"):
                if not consent:
                    st.error("Tick the box to confirm you want this CV's text kept on this computer.",
                             icon=":material/error:")
                else:
                    tailored_cv = ActiveCV(f"{slug}.{cv.extraction.kind}", len(final.encode()),
                                           hashlib.sha256(final.encode()).hexdigest(), datetime.now(timezone.utc),
                                           ExtractionResult(final, cv.extraction.kind, cv.extraction.page_count))
                    try:
                        with session_scope(settings.database_url) as s:
                            save_version(s, tailored_cv, version_name, f"Tailored for {name}"[:300])
                        st.success(f"Saved “{version_name.strip()}”. Find it on the CV Versions page.",
                                   icon=":material/check_circle:")
                    except VersionError as exc:
                        st.error(str(exc), icon=":material/error:")

    _apply_section(match, key)
