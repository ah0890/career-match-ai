"""Recruitment progress: counting rules, "No Response", the dashboard summary and safe automatic updates.

Counting rules (each application is counted once per card, however far it progressed):

* **Total applications** — every application you have applied for (anything after Saved / To Apply).
* **Active** — applied, and not Rejected or Withdrawn.
* **Pending a response** — Application Submitted or Application Received, within the no-response period.
* **Under review** — current status Under Review.
* **Interviews received** — applications with at least one interview (an interview that led to an offer
  still counts here).
* **Interviews scheduled** — current status Interview Scheduled.
* **Offers received** — applications with at least one offer.
* **Rejections** — current status Rejected.
* **No response** — Application Submitted or Received with no activity for the no-response period.
  "Pending a response" and "No response" never overlap.

Interview count of one application: each invitation counts once, and a "scheduled" event counts only if
no invitation is waiting for it (so invitation + scheduling of the same interview is one interview).
The user's own correction always wins over the automatic count.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from src.db.models import Application
from src.tracker.repository import (
    APPLIED, CLOSED, STATUS_RANK, WAITING, _aware, _now, _record_status, add_event,
)

NO_RESPONSE = "No Response"  # shown, never stored: it depends on today's date
HIGH_IMPACT = ("Interview Invitation", "Interview Scheduled", "Offer Received", "Rejected")


def interview_count(app: Application) -> int:
    if app.interviews_override is not None:
        return app.interviews_override
    count, waiting = 0, False
    for e in sorted(app.events, key=lambda e: _aware(e.occurred_at)):
        if e.kind == "Interview Invitation":
            count, waiting = count + 1, True
        elif e.kind == "Interview Scheduled":
            count, waiting = (count, False) if waiting else (count + 1, False)
    if count == 0 and app.status in ("Interview Scheduled", "Interview Completed", "Interview Invitation"):
        count = 1  # e.g. status set by hand without a timeline event
    return count


def offer_count(app: Application) -> int:
    if app.offers_override is not None:
        return app.offers_override
    count = sum(e.kind == "Offer Received" for e in app.events)
    return max(count, 1 if app.status == "Offer Received" else 0)


def waiting_since(app: Application) -> datetime | None:
    return _aware(app.last_activity_at) or _aware(app.applied_at) or _aware(app.updated_at)


def is_no_response(app: Application, now: datetime, days: int) -> bool:
    since = waiting_since(app)
    return app.status in WAITING and since is not None and now - since >= timedelta(days=days)


def current_status(app: Application, now: datetime, days: int) -> str:
    return NO_RESPONSE if is_no_response(app, now, days) else app.status


@dataclass(frozen=True)
class TrackingSummary:
    total: int
    active: int
    pending: int
    under_review: int
    interviews_received: int
    interviews_scheduled: int
    offers: int
    rejections: int
    no_response: int
    interview_events: int  # all interviews across applications (an application can have several)


def tracking_summary(apps: list[Application], now: datetime | None = None, no_response_days: int = 21) -> TrackingSummary:
    now = now or datetime.now(timezone.utc)
    applied = [a for a in apps if a.status in APPLIED]
    no_response = [a for a in applied if is_no_response(a, now, no_response_days)]
    interviews = [interview_count(a) for a in applied]
    return TrackingSummary(
        total=len(applied),
        active=sum(a.status not in CLOSED for a in applied),
        pending=sum(a.status in WAITING for a in applied) - len(no_response),
        under_review=sum(a.status == "Under Review" for a in applied),
        interviews_received=sum(n > 0 for n in interviews),
        interviews_scheduled=sum(a.status == "Interview Scheduled" for a in applied),
        offers=sum(offer_count(a) > 0 for a in applied),
        rejections=sum(a.status == "Rejected" for a in applied),
        no_response=len(no_response),
        interview_events=sum(interviews),
    )


@dataclass(frozen=True)
class Decision:
    changed: bool
    reason: str


def apply_detected(app: Application, kind: str, *, occurred_at: datetime, summary: str, confidence: float,
                   message_id: int | None = None, confirmed_by_user: bool = False) -> Decision:
    """Record an email-detected event and move the status forward when it is safe to.

    The event is always added to the timeline. The status changes only when:
    * the event is newer than the user's own last status change (manual corrections are never overwritten
      by sync; the user confirming an email in the review queue is itself a manual decision),
    * it moves the application forward in the process — a late "we received your application" never
      undoes an interview — except a rejection, which ends any open stage except an offer,
    * and the application is not closed (Rejected / Withdrawn).
    """
    occurred_at = _aware(occurred_at) or _now()
    add_event(app, kind, occurred_at=occurred_at, summary=summary, source="email",
              message_id=message_id, confidence=confidence)
    if kind not in STATUS_RANK:
        return Decision(False, "recorded on the timeline")
    manual = _aware(app.status_set_manually_at)
    if not confirmed_by_user and manual is not None and occurred_at <= manual:
        return Decision(False, "you set the status yourself after this email")
    if app.status in CLOSED:
        return Decision(False, f"the application is {app.status.lower()}")
    if kind == "Rejected":
        if app.status == "Offer Received":
            return Decision(False, "a rejection after an offer needs your review")
    elif STATUS_RANK[kind] <= STATUS_RANK[app.status]:
        return Decision(False, f"the application is already at {app.status}")
    _record_status(app, kind, occurred_at, None)
    return Decision(True, f"status updated to {kind}")
