"""CV Analysis — upload, extraction and (next) structure/ATS analysis."""

from __future__ import annotations

import math

import streamlit as st

from config.settings import get_settings
from src.cv.ats import analyse_cv
from src.cv.extraction import CVError
from src.cv.parsing import parse_cv
from src.cv.session import ActiveCV, delete_active_cv, get_active_cv, process_upload, set_active_cv
from src.matching.engine import profile_from
from src.services.matching import clear_matches
from src.ui.components import Feature, badge_html, feature_grid, key_value, notice, page_header, section_header
from src.ui.cv_report import render_ats, render_job_compare, render_skills, render_structure

_UPLOADER_GEN = "cv_uploader_gen"
_LAST_FILE_ID = "cv_last_file_id"
_LAST_ERROR = "cv_last_error"
_CONFIRM_DELETE = "cv_confirm_delete"
_FLASH = "cv_flash"


def _format_size(n: int) -> str:
    return f"{n / 1024:.0f} KB" if n < 1024 * 1024 else f"{n / (1024 * 1024):.1f} MB"


def _reset_uploader() -> None:
    st.session_state[_UPLOADER_GEN] = st.session_state.get(_UPLOADER_GEN, 0) + 1
    st.session_state.pop(_LAST_FILE_ID, None)
    st.session_state.pop(_LAST_ERROR, None)


def _handle_upload(max_bytes: int, max_mb: float, has_cv: bool) -> None:
    label = "Replace your CV" if has_cv else "Upload your CV"
    uploaded = st.file_uploader(
        label,
        type=["pdf", "docx"],
        key=f"cv_uploader_{st.session_state.get(_UPLOADER_GEN, 0)}",
        help=f"PDF or DOCX, up to {max_mb:g} MB. Processed on this computer only.",
        max_upload_size=max(1, math.ceil(max_mb)),
    )
    if uploaded is None:
        st.session_state.pop(_LAST_ERROR, None)
        return
    if uploaded.file_id == st.session_state.get(_LAST_FILE_ID):
        if err := st.session_state.get(_LAST_ERROR):  # keep showing why this file was rejected
            st.error(err, icon=":material/error:")
        return
    st.session_state[_LAST_FILE_ID] = uploaded.file_id
    st.session_state.pop(_LAST_ERROR, None)
    with st.spinner("Reading your CV…"):
        try:
            cv = process_upload(uploaded.name, uploaded.getvalue(), max_bytes)
        except CVError as exc:
            message = str(exc)
        except Exception:  # never surface internals or CV content
            message = "Something went wrong while reading this file. Try saving it again as PDF or DOCX."
        else:
            message = None
    if message:
        st.session_state[_LAST_ERROR] = message
        st.error(message, icon=":material/error:")
        return
    set_active_cv(st.session_state, cv)
    st.session_state.pop("cv_job_result", None)
    if cv.extraction.is_usable:
        st.session_state[_FLASH] = f"Text extracted from {cv.filename}."
    _reset_uploader()
    st.rerun()


def _summary(cv: ActiveCV) -> None:
    ex = cv.extraction
    if ex.needs_ocr:
        status = badge_html("Needs OCR", "warning")
    elif ex.is_usable:
        status = badge_html("Text extracted", "success")
    else:
        status = badge_html("Limited text", "warning")
    st.html(f'<div class="cm-badge-row">{badge_html(ex.kind.upper(), "neutral")}{status}</div>')
    rows = [("File", cv.filename), ("Size", _format_size(cv.size_bytes))]
    if ex.page_count is not None:
        rows.append(("Pages", str(ex.page_count)))
    rows += [("Words extracted", f"{ex.word_count:,}"),
             ("Uploaded", cv.uploaded_at.astimezone().strftime("%d %b %Y, %H:%M"))]
    key_value(rows)

    if ex.needs_ocr:
        notice(
            "This document appears to be a scanned image, so its text cannot be read. Optical character "
            "recognition (OCR) is not available in CareerMatch AI. Export your CV from the original editor "
            "(Word, Google Docs, etc.) as a text-based PDF or DOCX and upload that file instead.",
            tone="warning", title="Scanned document detected.",
        )
    for w in ex.warnings:
        notice(w, tone="warning")

    if ex.text:
        with st.expander("View extracted text"):
            st.caption("This is the text CareerMatch AI can read from your file. Missing or jumbled content "
                       "here usually means automated systems may struggle to read it too.")
            st.code(ex.text, language=None, wrap_lines=True, height=420)


def _delete_controls() -> None:
    if not st.session_state.get(_CONFIRM_DELETE):
        if st.button("Delete CV", icon=":material/delete:", key="cv_delete"):
            st.session_state[_CONFIRM_DELETE] = True
            st.rerun()
        return
    notice("Delete this CV and its extracted text from the current session? This cannot be undone.",
           tone="danger")
    c1, c2, _ = st.columns([1, 1, 3])
    if c1.button("Yes, delete", type="primary", icon=":material/delete_forever:", key="cv_delete_yes",
                 width="stretch"):
        delete_active_cv(st.session_state)
        clear_matches(st.session_state)
        for key in (_CONFIRM_DELETE, "cv_job_result", "cv_job_text", "cv_job_title"):
            st.session_state.pop(key, None)
        _reset_uploader()
        st.session_state[_FLASH] = "Your CV was deleted."
        st.rerun()
    if c2.button("Cancel", key="cv_delete_no", width="stretch"):
        st.session_state.pop(_CONFIRM_DELETE, None)
        st.rerun()


def render() -> None:
    settings = get_settings()
    page_header(
        "CV Analysis",
        "Check how clearly your CV communicates your experience and how reliably software can read it.",
        eyebrow="Discover",
    )
    flash = st.session_state.pop(_FLASH, None)
    if flash:
        st.toast(flash, icon=":material/check_circle:")

    cv = get_active_cv(st.session_state)
    with st.container(border=True):
        _handle_upload(settings.max_upload_bytes, settings.max_upload_mb, has_cv=cv is not None)
        st.caption("Your CV is processed in memory on this computer and nothing is sent to external services. "
                   "The original file is not stored; the extracted text is kept only for this browser session "
                   "and is cleared when you delete it, refresh or close the page — unless you choose to save it "
                   "on the CV Versions page.")

    if cv is None:
        section_header("What the analysis will include")
        feature_grid([
            Feature("ATS compatibility", "A transparent score out of 100 with a breakdown of how it was "
                    "calculated. It estimates readability, not the result of any specific employer's ATS."),
            Feature("Structure and formatting", "Section detection, heading consistency, date formats and "
                    "formatting patterns that commonly cause parsing problems."),
            Feature("Skills and keywords", "Technical and soft skills found in your CV, and keyword gaps "
                    "against a target job description."),
            Feature("Prioritised improvements", "Practical suggestions based only on what your CV actually "
                    "contains — never invented achievements."),
        ])
        return

    section_header("Your CV")
    _summary(cv)
    st.write("")
    _delete_controls()

    if cv.extraction.needs_ocr:
        return
    parsed = parse_cv(cv.extraction.text)
    report = analyse_cv(cv.extraction, parsed)
    section_header("Analysis")
    tab_ats, tab_structure, tab_skills, tab_job = st.tabs(
        ["ATS compatibility", "Structure and details", "Skills", "Compare with a job"]
    )
    with tab_ats:
        render_ats(report)
    with tab_structure:
        render_structure(parsed)
    with tab_skills:
        render_skills(parsed)
    with tab_job:
        render_job_compare(profile_from(cv.extraction.text, parsed, report), settings.scoring_weights)
