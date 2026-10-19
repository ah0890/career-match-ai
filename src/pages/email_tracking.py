"""Email Tracking — connect a mailbox (read-only) and keep the Application Tracker up to date from it."""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import streamlit as st
from sqlalchemy import select

from config.settings import get_settings
from src.db.engine import session_scope
from src.db.models import MailMessage, SyncRun
from src.jobs.models import safe_url
from src.mail import oauth, review, vault
from src.mail.sync import connect_account, disconnect, http_client
from src.services import mail as mail_service
from src.tracker.repository import APPLIED, EVENT_KINDS, PRE_APPLICATION, TrackerError, list_applications
from src.ui.components import Feature, empty_state, feature_grid, notice, page_header, section_header

_FLOW = "et_flow"
_FLASH = "et_flash"
_STATUS = {"ok": ("Up to date", "success"), "never": ("Not synced yet", "neutral"),
           "error": ("Last sync failed", "warning"), "reconnect": ("Needs reconnecting", "danger")}
_REVIEW_KINDS = [k for k in EVENT_KINDS if k not in PRE_APPLICATION]


def _db() -> str:
    return get_settings().database_url


def _ago(when: datetime | None) -> str:
    if when is None:
        return "never"
    when = when if when.tzinfo else when.replace(tzinfo=timezone.utc)
    minutes = int((datetime.now(timezone.utc) - when).total_seconds() // 60)
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes} min ago"
    return f"{minutes // 60} h ago" if minutes < 1440 else f"{when:%d %b %Y, %H:%M}"


def _report(run) -> None:
    if run.status == "ok":
        st.session_state[_FLASH] = (f"Synced: {run.new} new email(s), {run.matched} matched, "
                                    f"{run.review} to review.", "success")
    else:
        st.session_state[_FLASH] = (run.error or "The sync did not complete.", "warning")


# --- connect --------------------------------------------------------------------

def _configured(key: str) -> bool:
    try:
        oauth.client_credentials(oauth.PROVIDERS[key], get_settings())
        return True
    except oauth.OAuthError:
        return False


def _connect_section() -> None:
    section_header("Connect a mailbox", "Read-only access through Google's or Microsoft's own sign-in page. "
                                        "CareerMatch never sees your password and never sends or changes email.")
    flow: oauth.LoopbackFlow | None = st.session_state.get(_FLOW)
    if flow is None:
        c1, c2 = st.columns(2)
        for col, key, label in ((c1, "gmail", "Connect Gmail"), (c2, "outlook", "Connect Outlook / Microsoft 365")):
            ready = _configured(key)
            if col.button(label, key=f"et_connect_{key}", icon=":material/link:", disabled=not ready,
                          type="primary" if ready else "secondary", width="stretch",
                          help=None if ready else "Needs a one-time setup — see “Set up email access” below."):
                cid, _ = oauth.client_credentials(oauth.PROVIDERS[key], get_settings())
                new_flow = oauth.LoopbackFlow(oauth.PROVIDERS[key], cid)
                new_flow.start()
                st.session_state[_FLOW] = new_flow
                st.rerun()
        return
    st.info(f"Sign in with {flow.provider.label} in the new tab, allow read-only access, then come back here.",
            icon=":material/open_in_new:")
    b1, b2 = st.columns([2, 1])
    b1.link_button(f"Open {flow.provider.label} sign-in", flow.auth_url, type="primary", width="stretch")
    if b2.button("Cancel", key="et_cancel", width="stretch"):
        st.session_state.pop(_FLOW, None)
        st.rerun()
    _await_sign_in()


@st.fragment(run_every=2)
def _await_sign_in() -> None:
    flow: oauth.LoopbackFlow | None = st.session_state.get(_FLOW)
    if flow is None or not flow.finished:
        st.caption("Waiting for you to finish signing in…")
        return
    st.session_state.pop(_FLOW, None)
    if flow.error:
        st.session_state[_FLASH] = (f"Sign-in did not complete: {flow.error}", "warning")
        st.rerun()
    settings = get_settings()
    _, secret = oauth.client_credentials(flow.provider, settings)
    try:
        with http_client(settings) as client:
            token = oauth.exchange_code(flow, secret, client)
            with session_scope(settings.database_url) as s:
                account = connect_account(s, flow.provider.key, token, client)
                account_id, address = account.id, account.address
    except Exception as exc:  # OAuthError / MailError carry user-safe messages
        st.session_state[_FLASH] = (str(exc) if isinstance(exc, (oauth.OAuthError, RuntimeError))
                                    else "Connecting the mailbox failed. Try again.", "warning")
        st.rerun()
    run = mail_service.sync_now(account_id, trigger="manual")
    _report(run)
    st.session_state[_FLASH] = (f"Connected {address}. " + st.session_state[_FLASH][0], st.session_state[_FLASH][1])
    st.rerun()


# --- accounts -------------------------------------------------------------------

def _accounts_section(accounts) -> None:
    section_header("Connected mailboxes")
    for account in accounts:
        label, tone = _STATUS.get(account.sync_status, ("Unknown", "neutral"))
        with st.container(border=True):
            c1, c2 = st.columns([3, 2], vertical_alignment="center")
            c1.markdown(f"**{account.address}**  \n{oauth.PROVIDERS[account.provider].label} · "
                        f"last successful sync {_ago(account.last_sync_at)}")
            c2.badge(label, color={"success": "green", "warning": "orange", "danger": "red"}.get(tone, "gray"))
            if account.last_error:
                st.caption(account.last_error)
            b1, b2, b3 = st.columns(3)
            if b1.button("Sync emails now", key=f"et_sync_{account.id}", icon=":material/sync:", type="primary",
                         width="stretch", disabled=account.sync_status == "reconnect"):
                with st.spinner("Reading your recent emails…"):
                    _report(mail_service.sync_now(account.id))
                st.rerun()
            if b2.button("Reconnect", key=f"et_reconnect_{account.id}", icon=":material/link:", width="stretch",
                         disabled=not _configured(account.provider)):
                cid, _ = oauth.client_credentials(oauth.PROVIDERS[account.provider], get_settings())
                flow = oauth.LoopbackFlow(oauth.PROVIDERS[account.provider], cid)
                flow.start()
                st.session_state[_FLOW] = flow
                st.rerun()
            with b3.popover("Disconnect", icon=":material/link_off:", width="stretch"):
                st.write("Removes the saved sign-in and every synchronised email from this computer.")
                drop = st.checkbox("Also remove timeline events that came from this mailbox",
                                   key=f"et_drop_{account.id}")
                if st.button("Disconnect mailbox", key=f"et_disconnect_{account.id}", type="primary"):
                    settings = get_settings()
                    client = None if settings.offline_mode else httpx.Client(timeout=settings.http_timeout_s)
                    try:
                        with session_scope(settings.database_url) as s:
                            disconnect(s, account.id, delete_email_history=drop, client=client)
                    finally:
                        if client is not None:
                            client.close()
                    st.session_state[_FLASH] = (f"Disconnected {account.address}.", "success")
                    st.rerun()


# --- review -----------------------------------------------------------------------

def _review_section() -> None:
    with session_scope(_db()) as s:
        queue = review.review_queue(s)
        apps = [a for a in list_applications(s) if a.status in APPLIED or a.contact_email]
    section_header(f"Needs your review ({len(queue)})",
                   "Emails that look job-related but could not be matched or classified with confidence. "
                   "Nothing changes in your tracker until you confirm.")
    if not queue:
        st.caption("Nothing to review.")
        return
    labels = {a.id: f"{a.title} — {a.company or 'company not provided'}" for a in apps}
    for msg in queue[:25]:
        _review_item(msg, labels)


def _review_item(msg: MailMessage, labels: dict[int, str]) -> None:
    with st.container(border=True):
        sent = msg.sent_at.strftime("%d %b %Y") if msg.sent_at else ""
        st.markdown(f"**{msg.subject or '(no subject)'}**  \n"
                    f"{'From ' + (msg.from_name or msg.from_address or 'unknown') if msg.direction == 'in' else 'Sent by you'}"
                    f" · {sent}")
        if msg.snippet:
            st.caption(msg.snippet)
        suggestion = []
        if msg.kind:
            suggestion.append(f"looks like **{msg.kind}**" + (f" ({round(100 * msg.confidence)}%)"
                                                              if msg.confidence is not None else ""))
        if msg.application_id in labels:
            suggestion.append(f"probably **{labels[msg.application_id]}**")
        if suggestion:
            st.markdown("Suggestion: " + ", ".join(suggestion) + (f" — {msg.reason}" if msg.reason else ""))
        options = list(labels)
        c1, c2 = st.columns([3, 2])
        app_id = c1.selectbox("Application", options, format_func=labels.get, key=f"et_app_{msg.id}",
                              index=options.index(msg.application_id) if msg.application_id in options else None,
                              placeholder="Choose the application")
        kind = c2.selectbox("What it is", _REVIEW_KINDS, key=f"et_kind_{msg.id}",
                            index=_REVIEW_KINDS.index(msg.kind) if msg.kind in _REVIEW_KINDS else 0)
        b1, b2, b3, b4 = st.columns(4)
        if b1.button("Confirm", key=f"et_ok_{msg.id}", type="primary", icon=":material/check:", width="stretch",
                     disabled=app_id is None):
            with session_scope(_db()) as s:
                outcome = review.confirm(s, msg.id, app_id, kind)
            st.session_state[_FLASH] = (f"Linked to {labels[app_id]} — {outcome}.", "success")
            st.rerun()
        if b2.button("Not job-related", key=f"et_no_{msg.id}", icon=":material/block:", width="stretch"):
            with session_scope(_db()) as s:
                review.dismiss(s, msg.id)
            st.session_state[_FLASH] = ("Dismissed. Its content was removed and it will not be analysed again.",
                                        "success")
            st.rerun()
        with b3.popover("New application", icon=":material/add:", width="stretch"):
            title = st.text_input("Job title", key=f"et_title_{msg.id}", max_chars=300)
            company = st.text_input("Company", key=f"et_company_{msg.id}", max_chars=300,
                                    value=(msg.from_name or "")[:300])
            if st.button("Create and link", key=f"et_create_{msg.id}", type="primary"):
                try:
                    with session_scope(_db()) as s:
                        review.create_application(s, msg.id, title, company or None, kind)
                    st.session_state[_FLASH] = (f"Started tracking {title.strip()}.", "success")
                    st.rerun()
                except TrackerError as exc:
                    st.error(str(exc), icon=":material/error:")
        if url := safe_url(msg.web_link):
            b4.link_button("Open email", url, icon=":material/open_in_new:", width="stretch")


# --- history & privacy ---------------------------------------------------------------

def _history_section() -> None:
    with session_scope(_db()) as s:
        runs = list(s.scalars(select(SyncRun).order_by(SyncRun.started_at.desc()).limit(10)))
    if not runs:
        return
    with st.expander("Sync history", icon=":material/history:"):
        st.dataframe([{"Started": r.started_at.strftime("%d %b %Y %H:%M"), "Trigger": r.trigger,
                       "Result": r.status, "New emails": r.new, "Matched": r.matched, "To review": r.review,
                       "Problem": r.error or ""} for r in runs], hide_index=True, width="stretch")


def _setup_help() -> None:
    with st.expander("Set up email access (one time)", icon=":material/settings:"):
        st.markdown(
            "Email access uses **your own** free app registration, so your data goes only between your computer "
            "and your email provider.\n\n"
            "**Gmail** — in Google Cloud Console: create a project → enable the *Gmail API* → *OAuth consent screen*: "
            "External, add yourself as a test user → *Credentials*: create an *OAuth client ID* of type "
            "**Desktop app**. Put its values in `.env`:\n"
            "```\nCAREERMATCH_GMAIL_CLIENT_ID=...\nCAREERMATCH_GMAIL_CLIENT_SECRET=...\n```\n"
            "**Outlook / Microsoft 365** — in Microsoft Entra admin center → *App registrations* → New: "
            "supported accounts *any organisation and personal Microsoft accounts*; add platform "
            "**Mobile and desktop applications** with redirect URI `http://127.0.0.1`; under *API permissions* add "
            "Microsoft Graph *Mail.Read* and *User.Read* (delegated). Put the Application (client) ID in `.env`:\n"
            "```\nCAREERMATCH_OUTLOOK_CLIENT_ID=...\n```\n"
            "Restart the app after editing `.env`. Full steps are in the README.")


def _privacy() -> None:
    with st.expander("What is read and stored", icon=":material/lock:"):
        st.markdown(
            "- **Access:** read-only (`gmail.readonly`, or Microsoft *Mail.Read*). CareerMatch cannot send, delete "
            "or change email.\n"
            "- **Read:** recent messages that look job-related (Gmail is asked only for those); their text is "
            "analysed in memory and never stored in full.\n"
            "- **Kept for job emails:** sender, subject, date, a short snippet and a link to the original.\n"
            "- **Kept for other emails:** only an id, so they are never read again.\n"
            f"- **Sign-in token:** encrypted; the key is kept in {vault.key_location()}.\n"
            "- **Remove everything:** *Disconnect* deletes the token and every synchronised email.")


# --- page -----------------------------------------------------------------------------

def render() -> None:
    page_header("Email Tracking",
                "Connect your mailbox once: replies to your applications update the Application Tracker "
                "automatically, and anything uncertain waits for your review.", eyebrow="Track")
    if flash := st.session_state.pop(_FLASH, None):
        (st.success if flash[1] == "success" else st.warning)(flash[0], icon=":material/info:")
    settings = get_settings()
    if settings.offline_mode:
        notice("Offline mode is on, so email cannot be synchronised. Set CAREERMATCH_OFFLINE_MODE=false in .env.",
               tone="warning")
    elif not st.session_state.get(_FLOW):
        runs = mail_service.auto_sync()
        if runs and any(r.new for r in runs):
            st.toast(f"Synced {sum(r.new for r in runs)} new email(s).", icon=":material/sync:")
    accounts = mail_service.accounts()
    if accounts:
        _accounts_section(accounts)
        _review_section()
    else:
        empty_state("No mailbox connected",
                    "Connect Gmail or Outlook to record your application emails and the replies to them: "
                    "confirmations, assessments, interviews, offers and rejections.")
        feature_grid([
            Feature("Read-only", "CareerMatch can read your job emails but can never send, delete or change mail."),
            Feature("Careful matching", "Replies are linked by conversation, sender and company — uncertain ones "
                                        "wait for your review instead of changing your tracker."),
            Feature("Your data", "Only job-related details are kept, on this computer. Disconnect removes them."),
        ])
    _connect_section()
    _setup_help()
    _history_section()
    _privacy()
