"""Email sync for the app pages: run now, or automatically when the configured interval has passed.

Automatic sync is paced by the last *attempt* (not the last success), so a mailbox that keeps
failing is not retried on every page view.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from config.settings import Settings, get_settings
from src.db.engine import session_scope
from src.db.models import MailAccount, MailMessage, SyncRun
from src.mail.oauth import OAuthError
from src.mail.providers import MailError
from src.mail.sync import build_provider, http_client, sync_account
from src.tracker.repository import _aware


def accounts() -> list[MailAccount]:
    with session_scope(get_settings().database_url) as s:
        return list(s.scalars(select(MailAccount).order_by(MailAccount.connected_at)))


def review_count() -> int:
    with session_scope(get_settings().database_url) as s:
        return s.scalar(select(func.count()).select_from(MailMessage).where(MailMessage.relevance == "review")) or 0


def sync_now(account_id: int, trigger: str = "manual") -> SyncRun:
    settings = get_settings()
    with session_scope(settings.database_url) as s:
        account = s.get(MailAccount, account_id)
        try:
            with http_client(settings) as client:
                return sync_account(s, account, build_provider(account, settings, client), settings, trigger=trigger)
        except (MailError, OAuthError) as exc:  # offline mode, or the app registration is missing from .env
            account.sync_status, account.last_error = "error", str(exc)[:300]
            run = SyncRun(account_id=account.id, trigger=trigger, status="error", error=str(exc)[:300],
                          finished_at=datetime.now(timezone.utc))
            s.add(run)
            return run


def _last_attempt(account_id: int, settings: Settings) -> datetime | None:
    with session_scope(settings.database_url) as s:
        return _aware(s.scalar(select(func.max(SyncRun.started_at)).where(SyncRun.account_id == account_id)))


def auto_sync() -> list[SyncRun]:
    """Sync every mailbox whose interval has passed. Returns the runs made (usually none)."""
    settings = get_settings()
    if settings.mail_auto_sync_minutes == 0 or settings.offline_mode:
        return []
    now = datetime.now(timezone.utc)
    runs = []
    for account in accounts():
        if account.sync_status == "reconnect":
            continue
        last = _last_attempt(account.id, settings)
        if last is None or now - last >= timedelta(minutes=settings.mail_auto_sync_minutes):
            runs.append(sync_now(account.id, trigger="auto"))
    return runs
