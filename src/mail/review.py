"""The user's corrections to synchronised email. Every action marks the message as confirmed by the
user, so no later sync changes it again.
"""

from __future__ import annotations

from datetime import timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from src.db.models import Application, ApplicationEvent, MailMessage
from src.tracker.recruitment import apply_detected
from src.tracker.repository import EVENT_KINDS, ApplicationInput, TrackerError, add_manual, get


def _message(session: Session, message_id: int) -> MailMessage:
    row = session.get(MailMessage, message_id)
    if row is None:
        raise TrackerError("That email is no longer in the list.")
    return row


def review_queue(session: Session) -> list[MailMessage]:
    return list(session.scalars(select(MailMessage).where(MailMessage.relevance == "review")
                                .order_by(MailMessage.sent_at.desc())))


def linked_messages(session: Session, application_id: int) -> list[MailMessage]:
    return list(session.scalars(select(MailMessage).where(MailMessage.application_id == application_id)
                                .order_by(MailMessage.sent_at)))


def _remove_events(session: Session, row: MailMessage) -> None:
    session.execute(delete(ApplicationEvent).where(ApplicationEvent.message_id == row.id))


def confirm(session: Session, message_id: int, application_id: int, kind: str) -> str:
    """Link the email to an application as an event of the given type; returns what happened to the status."""
    if kind not in EVENT_KINDS:
        raise TrackerError(f"Unknown event type: {kind}.")
    row = _message(session, message_id)
    app = get(session, application_id)
    _remove_events(session, row)  # a correction replaces whatever was recorded before
    row.application_id, row.kind, row.relevance, row.user_confirmed = app.id, kind, "matched", True
    row.reason = "confirmed by you"
    when = row.sent_at if row.sent_at.tzinfo else row.sent_at.replace(tzinfo=timezone.utc)
    decision = apply_detected(app, kind, occurred_at=when, summary=row.subject or kind, confidence=1.0,
                              message_id=row.id, confirmed_by_user=True)
    session.flush()
    return decision.reason


def unlink(session: Session, message_id: int) -> None:
    """Detach a wrongly matched email. Its timeline event is removed; the status is left for the user to set."""
    row = _message(session, message_id)
    _remove_events(session, row)
    row.application_id, row.relevance, row.user_confirmed = None, "review", True
    row.reason = "unlinked by you"


def dismiss(session: Session, message_id: int) -> None:
    """Not about a job application: forget its content, keep only its id so it is never analysed again."""
    row = _message(session, message_id)
    _remove_events(session, row)
    row.relevance, row.user_confirmed, row.application_id = "dismissed", True, None
    row.subject = row.snippet = row.from_name = row.to_addresses = row.reason = None


def create_application(session: Session, message_id: int, title: str, company: str | None, kind: str) -> Application:
    """Start tracking an application this email is about (e.g. one applied for outside CareerMatch)."""
    row = _message(session, message_id)
    contact = row.from_address if row.direction == "in" else (row.to_addresses or "").split(",")[0].strip() or None
    app = add_manual(session, ApplicationInput(title, company, status="Application Submitted",
                                               contact_email=contact, applied_at=row.sent_at))
    session.flush()
    if kind != "Application Submitted":
        confirm(session, message_id, app.id, kind)
    else:
        row.application_id, row.kind, row.relevance, row.user_confirmed = app.id, kind, "matched", True
    return app
