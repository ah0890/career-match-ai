"""Application Tracker — every application from saved to offer, with its full recruitment history."""

from __future__ import annotations

from datetime import datetime, time, timezone
from html import escape

import pandas as pd
import streamlit as st

from config.settings import get_settings
from src.db.engine import session_scope
from src.tracker.recruitment import (
    NO_RESPONSE, current_status, interview_count, offer_count, tracking_summary,
)
from src.tracker.repository import (
    APPLIED, EVENT_KINDS, INTERVIEW_STATUSES, STATUS_NAMES, STATUS_RANK, STATUSES, ApplicationInput, TrackerError, add_manual,
    correct_counts, delete, due_actions, get, list_applications, set_status, update_contact, update_details,
    update_interview,
)
from src.ui.components import Metric, badge_html, empty_state, metric_grid, notice, page_header, section_header
from src.ui.layouts import call_to_action
from src.ui.tracker_view import application_card_html, follow_up_label, timeline_html
from src.jobs.models import safe_url
from src.mail import review as mail_review
from src.services import mail as mail_service
from src.ui.navigation import go_to
from src.workspace import exports as cv_exports
from src.workspace import repository as cv_repo

_FLASH = "at_flash"
_SELECTED = "at_selected"
_PAGE = "at_page"
PER_PAGE = 20
SORTS = {
    "Latest activity": lambda a: a.last_activity_at or a.updated_at,
    "Applied on (newest)": lambda a: a.applied_at or datetime.min.replace(tzinfo=timezone.utc),
    "Company (A–Z)": lambda a: (a.company or "").lower(),
    "Status (process order)": lambda a: STATUS_NAMES.index(a.status),
}


def _db() -> str:
    return get_settings().database_url


def _flash(message: str) -> None:
    st.session_state[_FLASH] = message


def _utc(d, t: time | None = None) -> datetime | None:
    return datetime.combine(d, t or time(9, 0)).replace(tzinfo=timezone.utc) if d else None


def _latest_reply(app) -> str:
    replies = [e for e in app.events if e.source == "email"]
    if not replies:
        return "—"
    e = max(replies, key=lambda e: e.occurred_at.replace(tzinfo=None))
    return f"{e.kind}: {e.summary}"[:120]


# --- summary --------------------------------------------------------------

def _summary(apps) -> None:
    settings = get_settings()
    t = tracking_summary(apps, no_response_days=settings.tracker_no_response_days)
    metric_grid([
        Metric("Total applications", str(t.total), "Everything you have applied for"),
        Metric("Active", str(t.active), "Not rejected or withdrawn"),
        Metric("Pending a response", str(t.pending), "Submitted or received, still recent"),
        Metric("Under review", str(t.under_review)),
        Metric("Interviews received", str(t.interviews_received), f"{t.interview_events} interview(s) in total"),
        Metric("Interviews scheduled", str(t.interviews_scheduled)),
        Metric("Offers received", str(t.offers)),
        Metric("Rejections", str(t.rejections)),
        Metric("No response", str(t.no_response), f"Nothing for {settings.tracker_no_response_days}+ days"),
    ])
    with st.expander("How these numbers are counted"):
        st.markdown(
            "- Each application is counted **once per card**, however far it progressed — an interview that led "
            "to an offer counts under *Interviews received* and *Offers received*.\n"
            "- *Pending a response* and *No response* never overlap: an application moves to *No response* after "
            f"{settings.tracker_no_response_days} days without any activity.\n"
            "- An interview invitation and the scheduling of that same interview count as **one** interview.\n"
            "- Your own corrections of interview and offer counts always replace the automatic count.")


# --- add ------------------------------------------------------------------

def _add_form() -> None:
    with st.expander("Add an application manually", icon=":material/add:"):
        with st.form("at_add", clear_on_submit=True, border=False):
            c1, c2 = st.columns(2)
            title = c1.text_input("Job title", max_chars=300)
            company = c2.text_input("Company", max_chars=300)
            c3, c4, c5 = st.columns([2, 2, 2])
            url = c3.text_input("Link to the listing (optional)", max_chars=2048, placeholder="https://")
            location = c4.text_input("Location (optional)", max_chars=300)
            status = c5.selectbox("Status", STATUS_NAMES, index=STATUS_NAMES.index("Application Submitted"))
            c6, c7, c8 = st.columns([2, 2, 2])
            contact = c6.text_input("Sent to (email, optional)", max_chars=254, placeholder="jobs@example.com")
            subject = c7.text_input("Email subject (optional)", max_chars=300)
            applied = c8.date_input("Applied on", value=None, format="DD/MM/YYYY",
                                    help="Leave empty for today, if the status means you have applied.")
            notes = st.text_area("Notes (optional)", max_chars=5000, height=80)
            if st.form_submit_button("Add to tracker", type="primary", icon=":material/add:"):
                try:
                    with session_scope(_db()) as s:
                        add_manual(s, ApplicationInput(title, company, location, url or None, status, notes,
                                                       contact or None, subject or None,
                                                       _utc(applied) if status in APPLIED else None))
                    _flash(f"Added {title.strip()}.")
                    st.rerun()
                except TrackerError as exc:
                    st.error(str(exc), icon=":material/error:")


# --- table ------------------------------------------------------------------

def _filtered(apps):
    days = get_settings().tracker_no_response_days
    now = datetime.now(timezone.utc)
    c1, c2, c3 = st.columns([3, 3, 2])
    query = c1.text_input("Search", placeholder="Company or job title", key="at_query").strip().lower()
    options = [*STATUS_NAMES, NO_RESPONSE]
    statuses = c2.multiselect("Status", options, key="at_statuses", placeholder="All statuses")
    sort = c3.selectbox("Sort by", list(SORTS), key="at_sort")
    shown = [a for a in apps
             if (not query or query in f"{a.company or ''} {a.title}".lower())
             and (not statuses or current_status(a, now, days) in statuses)]
    reverse = sort in ("Latest activity", "Applied on (newest)")
    return sorted(shown, key=lambda a: _sort_key(SORTS[sort](a)), reverse=reverse)


def _sort_key(value):
    return value.replace(tzinfo=None) if isinstance(value, datetime) else value


def _table(apps) -> int | None:
    """Renders one page of the table; returns the id of the application the user selected."""
    days = get_settings().tracker_no_response_days
    now = datetime.now(timezone.utc)
    pages = max(1, -(-len(apps) // PER_PAGE))
    page = min(st.session_state.get(_PAGE, 1), pages)
    rows = apps[(page - 1) * PER_PAGE: page * PER_PAGE]
    frame = pd.DataFrame([{
        "Company": a.company or "Not provided",
        "Job title": a.title,
        "Applied on": a.applied_on or pd.NaT,
        "Current status": current_status(a, now, days),
        "Last activity": (a.last_activity_at or a.updated_at).date(),
        "Interviews": interview_count(a),
        "Offers": offer_count(a),
        "Latest reply": _latest_reply(a),
    } for a in rows])
    event = st.dataframe(
        frame, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
        key=f"at_table_{page}_{len(apps)}",
        column_config={
            "Applied on": st.column_config.DateColumn(format="DD MMM YYYY"),
            "Last activity": st.column_config.DateColumn(format="DD MMM YYYY"),
            "Latest reply": st.column_config.TextColumn(width="large"),
        })
    st.caption("Select a row to see its timeline and update it.")
    if pages > 1:
        p1, p2, p3 = st.columns([1, 2, 1])
        if p1.button("Previous", disabled=page <= 1, key="at_prev", icon=":material/chevron_left:"):
            st.session_state[_PAGE] = page - 1
            st.rerun()
        p2.markdown(f"<div style='text-align:center'>Page {page} of {pages}</div>", unsafe_allow_html=True)
        if p3.button("Next", disabled=page >= pages, key="at_next", icon=":material/chevron_right:"):
            st.session_state[_PAGE] = page + 1
            st.rerun()
    selected = event.selection.rows if event and event.selection else []
    return rows[selected[0]].id if selected else None


# --- details ------------------------------------------------------------------

def _details(app_id: int) -> None:
    with session_scope(_db()) as s:
        try:
            app = get(s, app_id)
        except TrackerError:
            st.session_state.pop(_SELECTED, None)
            return
        _ = (app.events, app.history, [e.message for e in app.events])  # load while the session is open
    st.html(application_card_html(app))
    timeline, emails_tab, status_tab, interview_tab, cv_tab, details_tab = st.tabs(
        ["Timeline", "Emails", "Status", "Interview", "CV", "Details"])
    with timeline:
        st.html(timeline_html(app.events))
    with emails_tab:
        _emails(app)
    with status_tab:
        _status_form(app)
    with interview_tab:
        _interview_form(app)
    with cv_tab:
        _cv_tab(app.id)
    with details_tab:
        _details_form(app)
        _delete(app)


def _cv_tab(app_id: int) -> None:
    """The CV used for this application: link one, see the exact revision sent, download it."""
    with session_scope(_db()) as s:
        app = get(s, app_id)
        linked = cv_exports.for_application(s, app)
        docs = [(d.id, cv_repo.label(d)) for d in cv_repo.list_docs(s)]
        suggested = cv_repo.suggest_for_job(s, app.job_key, app.title, app.company)
        linked_info = None
        if linked:
            doc, number, _ = linked
            linked_info = (doc.id, cv_repo.label(doc), number, app.cv_revision_number is not None)
    if not docs:
        st.caption("Upload your CV in CV Studio to link it to your applications.")
        return
    if linked_info:
        doc_id, label, number, pinned = linked_info
        st.markdown(f"**{escape(label)}** · revision {number}")
        st.caption("This exact revision was sent and stays retrievable, even if you edit the CV later." if pinned
                   else "When you mark the application as submitted, the current revision is kept with it.")
        c1, c2 = st.columns(2)
        for col, kind, label_ in ((c1, "pdf", "PDF"), (c2, "docx", "DOCX")):
            key = f"at_cv_{kind}_{app_id}"
            made = st.session_state.get(key)
            if made and made[0] == (doc_id, number):
                col.download_button(f"Download {label_}", made[1], file_name=made[2], mime=cv_exports.MIME[kind],
                                    key=f"{key}_dl", on_click="ignore", icon=":material/download:", width="stretch")
            elif col.button(f"Create {label_} of this CV", key=f"{key}_make", width="stretch"):
                with session_scope(_db()) as s:
                    app = get(s, app_id)
                    result = cv_exports.generate(s, cv_repo.get_doc(s, doc_id), kind, revision=number,
                                                 application=app)
                if result.ok:
                    st.session_state[key] = ((doc_id, number), result.data, result.filename)
                    st.rerun()
                st.error(result.error, icon=":material/error:")
        if st.button("Open in CV Studio", key=f"at_cv_open_{app_id}", icon=":material/edit_document:"):
            st.session_state["cs_doc_next"] = doc_id
            go_to("cv-studio")
    ids = [d[0] for d in docs]
    labels = dict(docs)
    default = ids.index(suggested.id) if suggested is not None and suggested.id in ids else 0
    with st.form(f"at_cv_link_{app_id}", border=False):
        pick = st.selectbox("CV for this application", ids, index=default, format_func=labels.get,
                            help="Suggested: a CV tailored for this job, otherwise your master CV.")
        ok = st.checkbox("Yes, use this CV for this application")
        if st.form_submit_button("Link CV"):
            if not ok:
                st.error("Tick the box to confirm.", icon=":material/error:")
            else:
                with session_scope(_db()) as s:
                    cv_repo.select_for_application(s, get(s, app_id), cv_repo.get_doc(s, pick))
                _flash("CV linked to this application.")
                st.rerun()


def _emails(app) -> None:
    with session_scope(_db()) as s:
        messages = mail_review.linked_messages(s, app.id)
    if not messages:
        st.caption("No emails are linked to this application. Connect your mailbox on the Email Tracking page, "
                   "or record the address you applied to under Details so replies can be matched.")
        return
    kinds = [k for k in EVENT_KINDS if k not in ("Saved", "To Apply")]
    for msg in messages:
        with st.container(border=True):
            who = "Sent by you" if msg.direction == "out" else f"From {msg.from_name or msg.from_address}"
            when = msg.sent_at.strftime("%d %b %Y") if msg.sent_at else ""
            st.markdown(f"**{msg.subject or '(no subject)'}**  \n{who} · {when} · recorded as **{msg.kind}**"
                        + (" (confirmed by you)" if msg.user_confirmed else ""))
            c1, c2, c3, c4 = st.columns([2, 1, 1, 1], vertical_alignment="bottom")
            kind = c1.selectbox("Recorded as", kinds, index=kinds.index(msg.kind) if msg.kind in kinds else 0,
                                key=f"at_mkind_{msg.id}")
            if c2.button("Save", key=f"at_msave_{msg.id}", width="stretch", disabled=kind == msg.kind):
                with session_scope(_db()) as s:
                    mail_review.confirm(s, msg.id, app.id, kind)
                _flash(f"Email recorded as {kind}.")
                st.rerun()
            if c3.button("Unlink", key=f"at_munlink_{msg.id}", width="stretch",
                         help="Not about this application: it moves to the review queue on the Email Tracking page."):
                with session_scope(_db()) as s:
                    mail_review.unlink(s, msg.id)
                _flash("Email unlinked. Check the status is still right.")
                st.rerun()
            if url := safe_url(msg.web_link):
                c4.link_button("Open email", url, width="stretch")


def _sync_bar() -> None:
    accounts = mail_service.accounts()
    if not accounts:
        return
    runs = mail_service.auto_sync()
    if runs and any(r.new for r in runs):
        st.toast(f"Email synced: {sum(r.matched for r in runs)} update(s).", icon=":material/sync:")
        accounts = mail_service.accounts()
    pending = mail_service.review_count()
    last = max((a.last_sync_at for a in accounts if a.last_sync_at), default=None)
    problems = [a for a in accounts if a.sync_status in ("error", "reconnect")]
    with st.container(border=True):
        c1, c2, c3 = st.columns([3, 1, 1], vertical_alignment="center")
        text = (f"**Email tracking** · {len(accounts)} mailbox(es) · last synced "
                f"{last.strftime('%d %b %Y, %H:%M') + ' UTC' if last else 'never'}")
        if pending:
            text += f" · **{pending} email(s) to review**"
        if problems:
            text += " · a mailbox needs attention"
        c1.markdown(text)
        if c2.button("Sync emails now", key="at_sync", icon=":material/sync:", width="stretch"):
            with st.spinner("Reading your recent emails…"):
                for account in accounts:
                    if account.sync_status != "reconnect":
                        mail_service.sync_now(account.id)
            _flash("Email sync finished.")
            st.rerun()
        if c3.button("Review" if pending else "Email settings", key="at_review", width="stretch"):
            go_to("email-tracking")


def _status_form(app) -> None:
    with st.form(f"at_status_{app.id}", border=False):
        status = st.selectbox("Status", STATUS_NAMES, index=STATUS_NAMES.index(app.status), key=f"at_status_sel_{app.id}")
        note = st.text_input("What happened (optional)", max_chars=300, placeholder="e.g. Recruiter called")
        st.caption("Your own changes are never overwritten by email sync with older information.")
        if st.form_submit_button("Update status", type="primary"):
            with session_scope(_db()) as s:
                set_status(s, app.id, status, note=note.strip() or None)
            _flash(f"{app.title}: status changed to {status}.")
            st.rerun()
    with st.form(f"at_counts_{app.id}", border=False):
        st.markdown("**Correct the counts** (only if the automatic count is wrong)")
        c1, c2, c3 = st.columns(3)
        interviews = c1.number_input("Interviews", 0, 50, value=interview_count(app))
        offers = c2.number_input("Offers", 0, 50, value=offer_count(app))
        automatic = c3.checkbox("Count automatically", value=app.interviews_override is None
                                and app.offers_override is None)
        if st.form_submit_button("Save counts"):
            with session_scope(_db()) as s:
                correct_counts(s, app.id, interviews=None if automatic else int(interviews),
                               offers=None if automatic else int(offers))
            _flash("Counts saved.")
            st.rerun()


def _interview_form(app) -> None:
    with st.form(f"at_interview_{app.id}", border=False):
        c1, c2 = st.columns(2)
        when = app.interview_at
        day = c1.date_input("Interview date", value=when.date() if when else None, format="DD/MM/YYYY")
        at = c2.time_input("Time", value=when.time() if when else time(9, 0), step=900)
        notes = st.text_area("Interview notes", value=app.interview_notes or "", max_chars=5000, height=120,
                             placeholder="Who you met, what was asked, what to follow up on")
        if st.form_submit_button("Save interview details", type="primary"):
            with session_scope(_db()) as s:
                update_interview(s, app.id, interview_at=_utc(day, at), interview_notes=notes)
                if day and STATUS_RANK[app.status] < STATUS_RANK["Interview Scheduled"]:
                    set_status(s, app.id, "Interview Scheduled", note=f"Interview on {day:%d %b %Y} at {at:%H:%M}")
            _flash("Interview details saved.")
            st.rerun()
    if app.status in INTERVIEW_STATUSES[:2] and st.button("Mark interview as completed", key=f"at_done_{app.id}",
                                                         icon=":material/task_alt:"):
        with session_scope(_db()) as s:
            set_status(s, app.id, "Interview Completed")
        _flash("Interview marked as completed.")
        st.rerun()


def _details_form(app) -> None:
    with st.form(f"at_edit_{app.id}", border=False):
        d1, d2, d3 = st.columns(3)
        applied_on = d1.date_input("Applied on", value=app.applied_on, format="DD/MM/YYYY")
        next_action = d2.text_input("Next action", value=app.next_action or "", max_chars=300,
                                    placeholder="e.g. Follow up with recruiter")
        next_on = d3.date_input("Reminder date", value=app.next_action_on, format="DD/MM/YYYY")
        e1, e2 = st.columns(2)
        contact = e1.text_input("Application sent to (email)", value=app.contact_email or "", max_chars=254,
                                help="Used to match your application email and the replies to it.")
        subject = e2.text_input("Application email subject", value=app.application_subject or "", max_chars=300)
        notes = st.text_area("Notes", value=app.notes or "", max_chars=5000, height=100)
        if st.form_submit_button("Save details", icon=":material/save:"):
            try:
                with session_scope(_db()) as s:
                    update_details(s, app.id, notes=notes, next_action=next_action, next_action_on=next_on,
                                   applied_on=applied_on)
                    update_contact(s, app.id, contact_email=contact, application_subject=subject)
                _flash("Details saved.")
                st.rerun()
            except TrackerError as exc:
                st.error(str(exc), icon=":material/error:")


def _delete(app) -> None:
    confirm_key = f"at_confirm_delete_{app.id}"
    if not st.session_state.get(confirm_key):
        if st.button("Delete application", key=f"at_delete_{app.id}", icon=":material/delete:"):
            st.session_state[confirm_key] = True
            st.rerun()
        return
    st.warning("Delete this application and its history? This cannot be undone.", icon=":material/warning:")
    b1, b2, _ = st.columns([1, 1, 2])
    if b1.button("Yes, delete", type="primary", key=f"at_delete_yes_{app.id}"):
        with session_scope(_db()) as s:
            delete(s, app.id)
        st.session_state.pop(confirm_key, None)
        st.session_state.pop(_SELECTED, None)
        _flash(f"Deleted {app.title}.")
        st.rerun()
    if b2.button("Cancel", key=f"at_delete_no_{app.id}"):
        st.session_state.pop(confirm_key, None)
        st.rerun()


# --- page -----------------------------------------------------------------------

def render() -> None:
    page_header(
        "Application Tracker",
        "Every application from saved to offer, with its full history. Connect your mailbox on the Email "
        "Tracking page to update it from your emails.",
        eyebrow="Track",
    )
    if msg := st.session_state.pop(_FLASH, None):
        st.toast(msg, icon=":material/check_circle:")
    if not get_settings().offline_mode:
        _sync_bar()
    with session_scope(_db()) as s:
        due = due_actions(s)
        apps = list_applications(s)
        for a in apps:
            _ = a.events  # load while the session is open

    if not apps:
        empty_state("No applications tracked yet",
                    "Save a job from Job Matches, create a tailored CV for a job in CV Studio, or add one manually below. "
                    "Opening a job link never marks it as applied.")
        _, mid, _ = st.columns([2, 1, 2])
        with mid:
            call_to_action("View job matches", "job-matches", key="at_cta", icon=":material/arrow_forward:",
                           stretch=True)
        _add_form()
        _legend()
        return

    _summary(apps)
    if due:
        notice("; ".join(f"{a.title} — {a.next_action or 'follow up'} ({follow_up_label(a)[0].lower()})"
                         for a in due[:5]), tone="warning", title="Follow-ups due soon.")
    _add_form()

    section_header("Applications")
    shown = _filtered(apps)
    if not shown:
        st.caption("No applications match your search or filters.")
    else:
        selected = _table(shown)
        if selected is not None:
            st.session_state[_SELECTED] = selected
    if (app_id := st.session_state.get(_SELECTED)) is not None and any(a.id == app_id for a in shown):
        _details(app_id)
    _legend()


def _legend() -> None:
    with st.expander("What the statuses mean"):
        rows = "".join(f"<li>{badge_html(name, tone)}<span>{escape(desc)}</span></li>" for name, tone, desc in STATUSES)
        rows += (f"<li>{badge_html(NO_RESPONSE, 'neutral')}<span>Shown, not stored: submitted or received with no "
                 f"activity for {get_settings().tracker_no_response_days} days.</span></li>")
        st.html(f'<ul class="cm-card cm-status-legend">{rows}</ul>')
