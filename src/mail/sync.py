"""Connecting mailboxes and synchronising them with the application tracker.

A sync reads messages since the last successful sync (with a one-day overlap) — or the last
``mail_initial_days`` days the first time — oldest first, so an outgoing application email is
linked before the replies to it. Every message is processed once: its provider id is recorded,
and a message already seen is skipped without being downloaded again.

* Linked + confident classification → the application's timeline and status are updated.
* Uncertain link or classification → the review queue (subject and a short snippet are kept).
* Unrelated → only the provider id is kept.

Progress is committed as it goes. If a sync fails part-way, the last-sync time is not moved,
so the next sync covers the same window and skips what was already processed.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from config.settings import Settings
from src.db.models import Application, ApplicationEvent, MailAccount, MailMessage, SyncRun
from src.mail import oauth, vault
from src.mail.classify import Classification, classify, strip_quoted
from src.mail.matching import SUGGEST, THREAD, Candidate, Match, match
from src.mail.providers import AuthExpired, GmailProvider, MailError, MailHttp, OutlookProvider
from src.mail.types import MailItem
from src.tracker.recruitment import apply_detected
from src.tracker.repository import APPLIED, CLOSED, OTHER_COMMUNICATION, PRE_APPLICATION, _aware

log = logging.getLogger(__name__)
COMMIT_EVERY = 20
SNIPPET = 300


def http_client(settings: Settings) -> httpx.Client:
    if settings.offline_mode:
        raise MailError("Offline mode is on, so email cannot be synchronised. Turn it off in your .env file.")
    return httpx.Client(timeout=settings.http_timeout_s, headers={"User-Agent": "CareerMatchAI/1.0"})


# --- accounts ---------------------------------------------------------------------

def build_provider(account: MailAccount, settings: Settings, client: httpx.Client):
    config = oauth.PROVIDERS[account.provider]
    client_id, secret = oauth.client_credentials(config, settings)
    state = {"token": vault.decrypt(account.token_ciphertext)}

    def refresh() -> str:
        try:
            state["token"] = oauth.refresh(config, state["token"], client_id, secret, client)
        except oauth.OAuthUnreachable as exc:
            raise MailError(str(exc)) from None
        except oauth.OAuthError:
            raise AuthExpired("Access to this mailbox has expired or was removed. Reconnect it.") from None
        account.token_ciphertext = vault.encrypt(state["token"])
        return state["token"]["access_token"]

    def token() -> str:
        return refresh() if time.time() >= state["token"].get("expires_at", 0) else state["token"]["access_token"]

    http = MailHttp(client, token, refresh)
    cls = GmailProvider if account.provider == "gmail" else OutlookProvider
    return cls(http, account.address)


def connect_account(session: Session, provider_key: str, token: dict, client: httpx.Client) -> MailAccount:
    """Store a newly authorised mailbox (or refresh the token of one connected before)."""
    config = oauth.PROVIDERS[provider_key]
    http = MailHttp(client, lambda: token["access_token"], lambda: token["access_token"])
    address = (GmailProvider if provider_key == "gmail" else OutlookProvider)(http).profile_address()
    account = session.scalar(select(MailAccount).where(MailAccount.provider == provider_key,
                                                       MailAccount.address == address))
    if account is None:
        account = MailAccount(provider=provider_key, address=address, scopes=" ".join(config.scopes))
        session.add(account)
    account.token_ciphertext = vault.encrypt(token)
    account.sync_status = "never" if account.last_sync_at is None else "ok"
    account.last_error = None
    session.flush()
    return account


def disconnect(session: Session, account_id: int, *, delete_email_history: bool, client: httpx.Client | None) -> None:
    """Forget a mailbox: its token, every synchronised message and, if asked, the timeline events from it."""
    account = session.get(MailAccount, account_id)
    if account is None:
        return
    if delete_email_history:
        ids = select(MailMessage.id).where(MailMessage.account_id == account_id)
        session.execute(delete(ApplicationEvent).where(ApplicationEvent.message_id.in_(ids)))
    if client is not None:
        try:
            oauth.revoke(oauth.PROVIDERS[account.provider], vault.decrypt(account.token_ciphertext), client)
        except vault.VaultError:
            pass
    session.delete(account)


# --- sync ----------------------------------------------------------------------------

@dataclass
class _Context:
    candidates: list[Candidate]
    threads: dict[str, int] = field(default_factory=dict)
    linked: dict[str, int] = field(default_factory=dict)


def _candidates(session: Session, now: datetime) -> list[Candidate]:
    stale = now - timedelta(days=120)
    apps = session.scalars(select(Application).where(Application.status.not_in(PRE_APPLICATION)
                                                     | Application.contact_email.is_not(None)))
    return [Candidate(a.id, a.title, a.company, a.contact_email, a.application_subject,
                      _aware(a.applied_at) or _aware(a.created_at))
            for a in apps
            if not (a.status in CLOSED and (_aware(a.last_activity_at) or _aware(a.updated_at)) < stale)]


def _context(session: Session, account: MailAccount, now: datetime) -> _Context:
    ctx = _Context(_candidates(session, now))
    rows = session.execute(select(MailMessage.thread_id, MailMessage.internet_id, MailMessage.application_id)
                           .where(MailMessage.account_id == account.id, MailMessage.application_id.is_not(None),
                                  MailMessage.relevance == "matched"))
    for thread_id, internet_id, app_id in rows:
        if thread_id:
            ctx.threads[thread_id] = app_id
        if internet_id:
            ctx.linked[internet_id] = app_id
    return ctx


def summarise(item: MailItem) -> str:
    subject = " ".join(item.subject.split())
    return (subject or " ".join(strip_quoted(item.text).split())[:160] or "(no subject)")[:300]


def _store(account: MailAccount, item: MailItem, relevance: str, *, cls: Classification | None = None,
           found: Match | None = None, kind: str | None = None) -> MailMessage:
    row = MailMessage(account_id=account.id, provider_id=item.provider_id, direction=item.direction,
                      relevance=relevance)
    if relevance in ("matched", "review"):
        row.thread_id, row.internet_id = item.thread_id, item.internet_id
        row.from_address, row.from_name = item.from_address, (item.from_name or "")[:200] or None
        row.to_addresses = ", ".join(item.to_addresses)[:1000] or None
        row.subject = item.subject[:300] or None
        row.snippet = " ".join(strip_quoted(item.text).split())[:SNIPPET] or None
        row.sent_at, row.web_link = item.sent_at, item.web_link
        row.kind = kind or (cls.kind if cls else None)
        row.confidence = cls.confidence if cls else None
        row.application_id = found.application_id if found else None
        row.match_confidence = found.confidence if found else None
        reasons = [r for r in ((found.reason if found else ""), (cls.reason if cls else "")) if r]
        row.reason = "; ".join(reasons)[:300] or None
    return row


def process(session: Session, account: MailAccount, item: MailItem, ctx: _Context) -> str:
    """Analyse one email; returns its relevance (matched / review / unrelated)."""
    found = match(item, ctx.candidates, threads=ctx.threads, linked_ids=ctx.linked)
    if item.direction == "out":
        if found.application_id is None or found.confidence < SUGGEST:
            session.add(_store(account, item, "unrelated"))
            return "unrelated"
        relevance = "matched" if found.automatic else "review"
        row = _store(account, item, relevance, found=found, kind="Application Submitted")
        session.add(row)
        session.flush()
        if relevance == "matched":
            app = session.get(Application, found.application_id)
            app.contact_email = app.contact_email or (item.to_addresses[0] if item.to_addresses else None)
            app.application_subject = app.application_subject or item.subject[:300] or None
            if app.status in PRE_APPLICATION:
                apply_detected(app, "Application Submitted", occurred_at=item.sent_at, summary=summarise(item),
                               confidence=found.confidence, message_id=row.id)
            _remember(ctx, item, app.id)
        return relevance

    cls = classify(item.subject, item.text)
    in_thread = found.confidence >= THREAD
    if not cls.is_recruitment and not in_thread:
        session.add(_store(account, item, "unrelated"))
        return "unrelated"
    kind = cls.kind or OTHER_COMMUNICATION
    confident = cls.auto_apply or (in_thread and kind == OTHER_COMMUNICATION)
    relevance = "matched" if found.automatic and confident else "review"
    row = _store(account, item, relevance, cls=cls, found=found, kind=kind)
    session.add(row)
    session.flush()
    if relevance == "matched":
        app = session.get(Application, found.application_id)
        decision = apply_detected(app, kind, occurred_at=item.sent_at, summary=summarise(item),
                                  confidence=min(cls.confidence, found.confidence) if cls.kind else found.confidence,
                                  message_id=row.id)
        row.reason = f"{row.reason or ''}; {decision.reason}".strip("; ")[:300]
        _remember(ctx, item, app.id)
    return relevance


def _remember(ctx: _Context, item: MailItem, app_id: int) -> None:
    if item.thread_id:
        ctx.threads[item.thread_id] = app_id
    if item.internet_id:
        ctx.linked[item.internet_id] = app_id


def sync_account(session: Session, account: MailAccount, provider, settings: Settings, *,
                 now: datetime | None = None, trigger: str = "manual",
                 on_progress: Callable[[int, int], None] | None = None) -> SyncRun:
    now = now or datetime.now(timezone.utc)
    run = SyncRun(account_id=account.id, trigger=trigger, started_at=now)
    session.add(run)
    session.commit()
    last = _aware(account.last_sync_at)
    since = last - timedelta(days=1) if last else now - timedelta(days=settings.mail_initial_days)
    try:
        ctx = _context(session, account, now)
        seen = set(session.scalars(select(MailMessage.provider_id).where(MailMessage.account_id == account.id)))
        companies = sorted({c.company for c in ctx.candidates if c.company})
        contacts = sorted({c.contact_email for c in ctx.candidates if c.contact_email})
        ids = list(dict.fromkeys(provider.message_ids(since, companies, contacts, settings.mail_max_per_sync)))
        run.fetched = len(ids)
        items = []
        for n, provider_id in enumerate(i for i in ids if i not in seen):
            items.append(provider.message(provider_id))
            if on_progress:
                on_progress(n + 1, len(ids))
        for n, item in enumerate(sorted(items, key=lambda i: i.sent_at), start=1):
            relevance = process(session, account, item, ctx)
            run.new += 1
            run.matched += relevance == "matched"
            run.review += relevance == "review"
            if n % COMMIT_EVERY == 0:
                session.commit()
        run.status = account.sync_status = "ok"
        account.last_sync_at, account.last_error = now, None
    except (AuthExpired, vault.VaultError) as exc:
        session.rollback()
        run.status = account.sync_status = "reconnect"
        run.error = account.last_error = str(exc)[:300]
    except (MailError, oauth.OAuthError) as exc:
        session.rollback()
        run.status = account.sync_status = "error"
        run.error = account.last_error = str(exc)[:300]
    except Exception:  # never let one bad message break the app; details stay out of the UI
        session.rollback()
        log.exception("Email sync failed")
        run.status = account.sync_status = "error"
        run.error = account.last_error = "Unexpected error while reading email. It will be retried next sync."
    run.finished_at = datetime.now(timezone.utc)
    session.add_all([run, account])
    session.commit()
    return run


def due_for_auto_sync(account: MailAccount, settings: Settings, now: datetime | None = None) -> bool:
    if settings.mail_auto_sync_minutes == 0 or account.sync_status == "reconnect":
        return False
    last = _aware(account.last_sync_at)
    now = now or datetime.now(timezone.utc)
    return last is None or now - last >= timedelta(minutes=settings.mail_auto_sync_minutes)
