"""Application Tracker — saved jobs through to offers."""

from __future__ import annotations

from html import escape

import streamlit as st

from src.ui.components import badge_html, page_header, section_header
from src.ui.layouts import empty_page_body

STATUSES: tuple[tuple[str, str, str], ...] = (
    ("Saved", "neutral", "Kept for later review."),
    ("To Apply", "info", "You intend to apply."),
    ("Applied", "info", "You confirmed you submitted an application."),
    ("Interview", "warning", "An interview is scheduled or in progress."),
    ("Rejected", "danger", "The application was unsuccessful."),
    ("Offer", "success", "You received an offer."),
)


def render() -> None:
    page_header(
        "Application Tracker",
        "Track every application from saved to offer, with notes and follow-up dates.",
        eyebrow="Track",
    )
    empty_page_body(
        empty_title="No applications tracked yet",
        empty_message="Save a job from your matches to start tracking it. Opening a job link never marks "
                      "it as applied — only you change a status.",
        cta_label="Find jobs", cta_target="find-jobs", cta_key="at_cta",
    )
    section_header("Application statuses")
    rows = "".join(
        f"<li>{badge_html(name, tone)}<span>{escape(desc)}</span></li>" for name, tone, desc in STATUSES
    )
    st.html(f'<ul class="cm-card cm-status-legend">{rows}</ul>')
