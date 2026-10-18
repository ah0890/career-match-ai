"""Rendering of the CV analysis report (ATS score, structure, skills, job comparison)."""

from __future__ import annotations

import streamlit as st

from src.cv.ats import ATSReport, JobAlignment, job_alignment
from src.cv.parsing import SECTION_LABELS, ParsedCV
from src.ui.components import ListItem, item_list, key_value, notice, section_header
from src.ui.score_components import Bar, bars_html, chips_html, score_card_html, score_tone

_PRIORITY_TONE = {"High": "danger", "Medium": "warning", "Low": "neutral"}
_CATEGORY_LABELS = {
    "technical": "Technical skills", "tool": "Tools and platforms", "methodology": "Methods and practices",
    "domain": "Domain knowledge and standards", "soft": "Professional skills", "language": "Languages",
}
_CORE_SECTIONS = ("summary", "experience", "education", "skills", "certifications", "projects", "languages")


def render_ats(report: ATSReport) -> None:
    left, right = st.columns([2, 3], gap="medium")
    with left:
        st.html(score_card_html(
            report.score, report.band, "ATS compatibility",
            "How reliably software can read and understand your CV. It is a formatting and structure check, "
            "not a prediction of any employer's decision.",
        ))
    with right:
        st.html(bars_html(
            Bar(c.label, c.score, c.max_score, c.description) for c in report.components
        ))

    section_header("Prioritised improvements")
    if report.recommendations:
        item_list(
            ListItem(r.title, r.detail, r.priority, _PRIORITY_TONE[r.priority],
                     f"{r.component} · up to {r.points_available:g} points")
            for r in report.recommendations
        )
    else:
        notice("No improvements were identified by these checks.", tone="success")

    with st.expander("How this score is calculated"):
        st.caption(report.limitations)
        for comp in report.components:
            st.markdown(f"**{comp.label}** — {comp.score:g} of {comp.max_score:g} points")
            item_list(
                ListItem(
                    c.label, c.detail,
                    "Met" if c.passed else ("Partly met" if c.points > 0 else "Not met"),
                    "success" if c.passed else ("warning" if c.points > 0 else "neutral"),
                    f"{c.points:g} / {c.max_points:g} points",
                )
                for c in comp.checks
            )


def render_structure(parsed: ParsedCV) -> None:
    section_header("Sections", "Recognised from the headings in your CV.")
    found = set(parsed.section_keys)
    item_list(
        ListItem(SECTION_LABELS[k],
                 f"Heading: “{parsed.section(k).heading}”" if k in found else "Not recognised in the CV text.",
                 "Found" if k in found else "Not found", "success" if k in found else "neutral")
        for k in (*_CORE_SECTIONS, *(k for k in parsed.section_keys if k not in _CORE_SECTIONS))
    )
    if parsed.unrecognised_headings:
        st.caption("Other headings detected: " + ", ".join(parsed.unrecognised_headings))
    for n in parsed.notes:
        notice(n, tone="warning")

    section_header("Details found", "Facts read directly from the text, and estimates clearly marked as such.")
    c = parsed.contact
    rows = [
        ("Name (estimated)", parsed.name_guess or "Not identified"),
        ("Email", ", ".join(c.emails) or "Not found"),
        ("Phone", ", ".join(c.phones) or "Not found"),
        ("Links", ", ".join(c.links[:3]) or "Not found"),
        ("Dated roles found", str(len(parsed.date_ranges))),
        ("Experience (estimated)",
         f"About {parsed.experience_years_estimate:g} years, from the date ranges found"
         if parsed.date_ranges else "Could not be estimated — no date ranges found"),
        ("Bullet points", str(parsed.bullets.total)),
        ("Words", f"{parsed.word_count:,}"),
    ]
    key_value(rows)
    st.caption("Estimates are inferred from your CV text and may be inaccurate. Anything marked “Not found” "
               "was not detected — it does not mean it is missing from your background.")


def render_skills(parsed: ParsedCV) -> None:
    if not parsed.skills:
        notice("No skills from the built-in skills dictionary were recognised in your CV.", tone="warning")
        return
    by_cat: dict[str, list[str]] = {}
    for s in parsed.skills:
        by_cat.setdefault(s.category, []).append(s.name)
    for cat, label in _CATEGORY_LABELS.items():
        if cat in by_cat:
            st.markdown(f"**{label}**")
            st.html(chips_html(by_cat[cat], "info"))
    st.caption(f"{len(parsed.skills)} skills recognised using a dictionary of common skills. Skills described in "
               "other words, or specialist skills not in the dictionary, may not appear here.")


def _render_alignment(a: JobAlignment) -> None:
    left, right = st.columns([2, 3], gap="medium")
    with left:
        st.html(score_card_html(
            a.score, "Unreliable" if not a.reliable else _alignment_band(a.score),
            "Job keyword alignment", a.note,
        ))
    with right:
        st.markdown("**Skills from the job found in your CV**")
        st.html(chips_html(a.matched_skills, "success", "None of the job's recognised skills were found."))
        st.markdown("**Skills from the job not found in your CV**")
        st.html(chips_html(a.missing_skills, "warning", "None — every recognised skill was found."))
        st.markdown("**Other frequent job terms found in your CV**")
        st.html(chips_html(a.matched_keywords, "success", "None."))
        st.markdown("**Other frequent job terms not found in your CV**")
        st.html(chips_html(a.missing_keywords, "neutral", "None."))
    notice("Only add a missing skill or term to your CV if it genuinely reflects your experience.", tone="info")


def _alignment_band(score: int) -> str:
    tone = score_tone(score)
    return {"success": "Strong alignment", "info": "Good alignment", "warning": "Partial alignment",
            "danger": "Low alignment"}[tone]


def render_job_compare(cv_text: str) -> None:
    st.caption("Paste a job description to see which of its skills and key terms appear in your CV. This is "
               "separate from the ATS score above, which measures formatting and structure only.")
    with st.form("cv_job_compare", border=False):
        jd = st.text_area("Job description", height=220, max_chars=20000, key="cv_job_text",
                          placeholder="Paste the full job description here…")
        go = st.form_submit_button("Compare with my CV", type="primary", icon=":material/compare_arrows:")
    if go:
        if len(jd.split()) < 15:
            st.error("Paste a longer job description (at least a few sentences) to compare.",
                     icon=":material/error:")
            st.session_state.pop("cv_job_result", None)
        else:
            st.session_state["cv_job_result"] = job_alignment(cv_text, jd)
    result = st.session_state.get("cv_job_result")
    if result is not None:
        _render_alignment(result)
