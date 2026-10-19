"""Application Tracker — saved jobs through to offers, stored on this computer."""

from __future__ import annotations

from html import escape

import streamlit as st

from config.settings import get_settings
from src.db.engine import session_scope
from src.tracker.repository import (
    ACTIVE, STATUS_NAMES, STATUSES, ApplicationInput, TrackerError, add_manual, delete, due_actions,
    list_applications, set_status, status_counts, update_details,
)
from src.ui.components import Metric, badge_html, empty_state, metric_grid, notice, page_header, section_header
from src.ui.layouts import call_to_action
from src.ui.tracker_view import application_card_html, follow_up_label

_FLASH = "at_flash"


def _db() -> str:
    return get_settings().database_url


def _flash(message: str) -> None:
    st.session_state[_FLASH] = message


def _add_form() -> None:
    with st.expander("Add a job manually", icon=":material/add:"):
        with st.form("at_add", clear_on_submit=True, border=False):
            c1, c2 = st.columns(2)
            title = c1.text_input("Job title", max_chars=300)
            company = c2.text_input("Company", max_chars=300)
            c3, c4, c5 = st.columns([2, 2, 1])
            url = c3.text_input("Link to the listing (optional)", max_chars=2048, placeholder="https://")
            location = c4.text_input("Location (optional)", max_chars=300)
            status = c5.selectbox("Status", STATUS_NAMES)
            notes = st.text_area("Notes (optional)", max_chars=5000, height=80)
            if st.form_submit_button("Add to tracker", type="primary", icon=":material/add:"):
                try:
                    with session_scope(_db()) as s:
                        add_manual(s, ApplicationInput(title, company, location, url or None, status, notes))
                    _flash(f"Added {title.strip()}.")
                    st.rerun()
                except TrackerError as exc:
                    st.error(str(exc), icon=":material/error:")


def _change_status(app_id: int, key: str) -> None:
    with session_scope(_db()) as s:
        app = set_status(s, app_id, st.session_state[key])
        _flash(f"{app.title}: status changed to {app.status}.")


def _application(app) -> None:
    st.html(application_card_html(app))
    c1, c2 = st.columns([1, 3])
    key = f"at_status_{app.id}"
    c1.selectbox("Status", STATUS_NAMES, index=STATUS_NAMES.index(app.status), key=key,
                 on_change=_change_status, args=(app.id, key), label_visibility="collapsed")
    with c2.expander("Details, notes and history"):
        with st.form(f"at_edit_{app.id}", border=False):
            d1, d2, d3 = st.columns(3)
            applied_on = d1.date_input("Applied on", value=app.applied_on, format="DD/MM/YYYY")
            next_action = d2.text_input("Next action", value=app.next_action or "", max_chars=300,
                                        placeholder="e.g. Follow up with recruiter")
            next_on = d3.date_input("Next action date", value=app.next_action_on, format="DD/MM/YYYY")
            notes = st.text_area("Notes", value=app.notes or "", max_chars=5000, height=100)
            if st.form_submit_button("Save details", icon=":material/save:"):
                with session_scope(_db()) as s:
                    update_details(s, app.id, notes=notes, next_action=next_action, next_action_on=next_on,
                                   applied_on=applied_on)
                _flash("Details saved.")
                st.rerun()
        if app.history:
            st.caption("History: " + " → ".join(
                f"{h.to_status} ({h.changed_at:%d %b %Y})" for h in app.history))
        confirm_key = f"at_confirm_delete_{app.id}"
        if not st.session_state.get(confirm_key):
            if st.button("Delete", key=f"at_delete_{app.id}", icon=":material/delete:"):
                st.session_state[confirm_key] = True
                st.rerun()
        else:
            st.warning("Delete this application and its history? This cannot be undone.", icon=":material/warning:")
            b1, b2, _ = st.columns([1, 1, 2])
            if b1.button("Yes, delete", type="primary", key=f"at_delete_yes_{app.id}"):
                with session_scope(_db()) as s:
                    delete(s, app.id)
                st.session_state.pop(confirm_key, None)
                _flash(f"Deleted {app.title}.")
                st.rerun()
            if b2.button("Cancel", key=f"at_delete_no_{app.id}"):
                st.session_state.pop(confirm_key, None)
                st.rerun()


def render() -> None:
    page_header(
        "Application Tracker",
        "Track every application from saved to offer, with notes and follow-up dates.",
        eyebrow="Track",
    )
    if msg := st.session_state.pop(_FLASH, None):
        st.toast(msg, icon=":material/check_circle:")
    with session_scope(_db()) as s:
        counts = status_counts(s)
        due = due_actions(s)
        apps = list_applications(s)

    if not apps:
        empty_state("No applications tracked yet",
                    "Save a job from Job Matches, or add one manually below. Opening a job link never marks it "
                    "as applied — only you change a status.")
        _, mid, _ = st.columns([2, 1, 2])
        with mid:
            call_to_action("View job matches", "job-matches", key="at_cta", icon=":material/arrow_forward:",
                           stretch=True)
        _add_form()
        _legend()
        return

    metric_grid([
        Metric("Active", str(sum(counts[s] for s in ACTIVE)), "Saved, to apply, applied or interviewing"),
        Metric("Applied", str(counts["Applied"]), "Waiting for a response"),
        Metric("Interviews", str(counts["Interview"])),
        Metric("Offers", str(counts["Offer"])),
    ])
    if due:
        notice("; ".join(f"{a.title} — {a.next_action or 'follow up'} ({follow_up_label(a)[0].lower()})"
                         for a in due[:5]), tone="warning", title="Follow-ups due soon.")
    _add_form()

    present = [s for s in STATUS_NAMES if counts[s]]
    # Keyed by the statuses present, so the filter resets when an application moves to a new status
    # instead of silently hiding it.
    shown = st.pills("Show", present, selection_mode="multi", default=[s for s in present if s in ACTIVE] or present,
                     key=f"at_filter_{'_'.join(present)}") or []
    visible = [a for a in apps if a.status in shown]
    section_header(f"{len(visible)} application{'s' if len(visible) != 1 else ''}",
                   "Stored only on this computer. Change a status yourself when something happens.")
    if not visible:
        st.caption("No applications with the selected statuses.")
    for app in visible:
        _application(app)
    _legend()


def _legend() -> None:
    with st.expander("What the statuses mean"):
        rows = "".join(f"<li>{badge_html(name, tone)}<span>{escape(desc)}</span></li>" for name, tone, desc in STATUSES)
        st.html(f'<ul class="cm-card cm-status-legend">{rows}</ul>')
