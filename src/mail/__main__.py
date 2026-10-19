"""Synchronise every connected mailbox without opening the app.

    python -m src.mail sync

Schedule it (e.g. hourly with Windows Task Scheduler or cron) to keep the tracker up to date even
when CareerMatch is closed. Prints counts only — never email content.
"""

from __future__ import annotations

import sys

from sqlalchemy import select

from config.settings import get_settings
from src.db.engine import session_scope
from src.db.models import MailAccount
from src.mail.providers import MailError
from src.mail.sync import build_provider, http_client, sync_account


def main(argv: list[str]) -> int:
    if argv[1:] != ["sync"]:
        print(__doc__.strip())
        return 2
    settings = get_settings()
    with session_scope(settings.database_url) as session:
        if session.scalars(select(MailAccount)).first() is None:
            print("No mailbox is connected. Connect one on the Email Tracking page.")
            return 0
    try:
        client = http_client(settings)
    except MailError as exc:
        print(exc)
        return 1
    failures = 0
    with client, session_scope(settings.database_url) as session:
        for account in session.scalars(select(MailAccount)).all():
            try:
                run = sync_account(session, account, build_provider(account, settings, client), settings, trigger="cli")
            except Exception as exc:  # e.g. the app registration was removed from .env
                print(f"{account.address}: {exc}")
                failures += 1
                continue
            print(f"{account.address}: {run.status} — {run.new} new, {run.matched} matched, {run.review} to review"
                  + (f" ({run.error})" if run.error else ""))
            failures += run.status != "ok"
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
