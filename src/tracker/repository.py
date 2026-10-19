"""Application tracker operations.

Opening a link never changes a status. Statuses change when the user sets them, or when a
synchronised email is classified with high confidence (see ``src.tracker.recruitment``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from src.db.models import Application, ApplicationEvent, StatusChange, StudyProgress
from src.jobs.models import JobPosting, safe_url
from src.matching.recommendations import RankedMatch

# In process order: automatic updates only ever move an application forward through this list.
STATUSES: tuple[tuple[str, str, str], ...] = (
    ("Saved", "neutral", "Kept for later review."),
    ("To Apply", "info", "You intend to apply."),
    ("Application Submitted", "info", "Your application was sent."),
    ("Application Received", "info", "The employer confirmed they received your application."),
    ("Under Review", "info", "The employer is reviewing your application."),
    ("Assessment", "warning", "You were invited to complete an assessment or test."),
    ("Interview Invitation", "warning", "You were invited to an interview."),
    ("Interview Scheduled", "warning", "An interview date and time are confirmed."),
    ("Interview Completed", "warning", "The interview has taken place."),
    ("Offer Received", "success", "You received a job offer."),
    ("Rejected", "danger", "The employer declined your application."),
    ("Withdrawn", "neutral", "You withdrew from the process."),
)
STATUS_NAMES = tuple(s for s, _, _ in STATUSES)
STATUS_TONES = {s: tone for s, tone, _ in STATUSES}
STATUS_RANK = {s: i for i, s in enumerate(STATUS_NAMES)}
PRE_APPLICATION = ("Saved", "To Apply")
APPLIED = tuple(s for s in STATUS_NAMES if s not in PRE_APPLICATION)  # the user has applied
WAITING = ("Application Submitted", "Application Received")  # applied, no progress yet
INTERVIEW_STATUSES = ("Interview Invitation", "Interview Scheduled", "Interview Completed")
CLOSED = ("Rejected", "Withdrawn")
ACTIVE = tuple(s for s in STATUS_NAMES if s not in CLOSED)
OTHER_COMMUNICATION = "Other Recruitment Communication"  # a timeline event, never a status
EVENT_KINDS = (*STATUS_NAMES, OTHER_COMMUNICATION)


class TrackerError(ValueError):
    """A user-correctable problem, e.g. an unknown status. The message is safe to show."""


@dataclass(frozen=True)
class ApplicationInput:
    title: str
    company: str | None = None
    location: str | None = None
    listing_url: str | None = None
    status: str = "Saved"
    notes: str | None = None
    contact_email: str | None = None
    application_subject: str | None = None
    applied_at: datetime | None = None


def _clean(text: str | None, limit: int) -> str | None:
    text = " ".join((text or "").split())
    return text[:limit] or None


def _check_status(status: str) -> str:
    if status not in STATUS_NAMES:
        raise TrackerError(f"Unknown status: {status}.")
    return status


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt  # SQLite drops tz


def clean_email(value: str | None) -> str | None:
    value = (value or "").strip().lower()
    if not value:
        return None
    if len(value) > 254 or value.count("@") != 1 or " " in value or "." not in value.split("@")[1]:
        raise TrackerError("Enter a valid email address, e.g. recruiter@example.com.")
    return value


def add_event(app: Application, kind: str, *, occurred_at: datetime | None = None,
              summary: str | None = None, source: str = "manual", message_id: int | None = None,
              confidence: float | None = None) -> ApplicationEvent:
    """Add a step to the application's timeline and move its last-activity date forward."""
    if kind not in EVENT_KINDS:
        raise TrackerError(f"Unknown event type: {kind}.")
    when = _aware(occurred_at) or _now()
    event = ApplicationEvent(kind=kind, occurred_at=when, summary=_clean(summary, 300) or kind, source=source,
                             message_id=message_id, confidence=confidence)
    app.events.append(event)
    last = _aware(app.last_activity_at)
    if last is None or when > last:
        app.last_activity_at = when
    return event


def _record_status(app: Application, status: str, when: datetime, today: date | None) -> None:
    app.history.append(StatusChange(from_status=app.status, to_status=status, changed_at=when))
    app.status = status
    if status in APPLIED and app.applied_on is None:
        app.applied_on = today or when.date()
        app.applied_at = app.applied_at or when
    if status in APPLIED and app.cv_doc_id and app.cv_revision_number is None:
        from sqlalchemy.orm import object_session

        from src.workspace.repository import pin_for_submission
        if (session := object_session(app)) is not None:
            pin_for_submission(session, app)  # keep the exact CV revision that was sent
    app.updated_at = _now()


def find_by_job(session: Session, job_key: str) -> Application | None:
    return session.scalar(select(Application).where(Application.job_key == job_key))


def save_job(session: Session, match: RankedMatch | None, job: JobPosting, status: str = "Saved") -> tuple[Application, bool]:
    """Save a job from search results. Returns (application, created); an existing entry is never duplicated."""
    existing = find_by_job(session, job.key)
    if existing is not None:
        return existing, False
    app = Application(
        job_key=job.key, title=job.title[:300], company=_clean(job.company, 300), location=_clean(job.location, 300),
        source_name=job.source_name[:100], listing_url=job.listing_url, apply_url=job.apply_url,
        description=job.description[:20000] or None, status=_check_status(status),
        match_score=float(match.result.score) if match else None,
        recommendation=match.recommendation.label.value if match else None,
    )
    app.history.append(StatusChange(from_status=None, to_status=app.status))
    add_event(app, app.status, summary=f"Saved from {job.source_name}" if status == "Saved" else None,
              source="app")
    session.add(app)
    session.flush()
    return app, True


def record_application(session: Session, match: RankedMatch | None, job: JobPosting, *,
                       contact_email: str | None = None, subject: str | None = None) -> Application:
    """The user confirms they applied (on the employer's site or by email). Never called automatically."""
    contact = clean_email(contact_email)
    app, _ = save_job(session, match, job)
    if contact or subject:
        app.contact_email = contact or app.contact_email
        app.application_subject = _clean(subject, 300) or app.application_subject
    if app.status in PRE_APPLICATION:
        how = f"by email to {contact}" if contact else "on the employer's site"
        set_status(session, app.id, "Application Submitted", note=f"Application submitted {how}")
    return app


def add_manual(session: Session, data: ApplicationInput) -> Application:
    title = _clean(data.title, 300)
    if not title or len(title) < 2:
        raise TrackerError("Enter a job title of at least 2 characters.")
    if data.listing_url and not safe_url(data.listing_url):
        raise TrackerError("The link must be a full http(s) address, e.g. https://example.com/job.")
    status = _check_status(data.status)
    applied_at = _aware(data.applied_at) or (_now() if status in APPLIED else None)
    app = Application(title=title, company=_clean(data.company, 300), location=_clean(data.location, 300),
                      source_name="Added manually", listing_url=safe_url(data.listing_url), status=status,
                      notes=(data.notes or "").strip()[:5000] or None, contact_email=clean_email(data.contact_email),
                      application_subject=_clean(data.application_subject, 300), applied_at=applied_at,
                      applied_on=applied_at.date() if applied_at else None,
                      status_set_manually_at=_now())
    app.history.append(StatusChange(from_status=None, to_status=status))
    add_event(app, status, occurred_at=applied_at if status in APPLIED else None,
              summary="Added manually" if status in PRE_APPLICATION else f"{status} (added manually)")
    session.add(app)
    session.flush()
    return app


def list_applications(session: Session, statuses: tuple[str, ...] | None = None) -> list[Application]:
    query = select(Application).options(selectinload(Application.history)).order_by(Application.updated_at.desc())
    if statuses:
        query = query.where(Application.status.in_(statuses))
    return list(session.scalars(query))


def get(session: Session, app_id: int) -> Application:
    app = session.get(Application, app_id)
    if app is None:
        raise TrackerError("That application no longer exists.")
    return app


def set_status(session: Session, app_id: int, status: str, today: date | None = None,
               note: str | None = None) -> Application:
    """The user's own status change. Later email syncs never overwrite it with older information."""
    app = get(session, app_id)
    status = _check_status(status)
    if status == app.status:
        return app
    when = _now()
    _record_status(app, status, when, today)
    app.status_set_manually_at = when
    add_event(app, status, occurred_at=when, summary=note or f"Status set to {status}")
    return app


def update_details(session: Session, app_id: int, *, notes: str | None, next_action: str | None,
                   next_action_on: date | None, applied_on: date | None) -> Application:
    app = get(session, app_id)
    app.notes = (notes or "").strip()[:5000] or None
    app.next_action = _clean(next_action, 300)
    app.next_action_on = next_action_on
    app.applied_on = applied_on
    app.updated_at = _now()
    return app


def update_contact(session: Session, app_id: int, *, contact_email: str | None,
                   application_subject: str | None) -> Application:
    """Where the application was sent: used to match the outgoing email and its replies."""
    app = get(session, app_id)
    app.contact_email = clean_email(contact_email)
    app.application_subject = _clean(application_subject, 300)
    app.updated_at = _now()
    return app


def update_interview(session: Session, app_id: int, *, interview_at: datetime | None,
                     interview_notes: str | None) -> Application:
    app = get(session, app_id)
    app.interview_at = _aware(interview_at)
    app.interview_notes = (interview_notes or "").strip()[:5000] or None
    app.updated_at = _now()
    return app


def correct_counts(session: Session, app_id: int, *, interviews: int | None, offers: int | None) -> Application:
    """The user's correction of the interview and offer counts; None returns to automatic counting."""
    for value in (interviews, offers):
        if value is not None and not 0 <= value <= 50:
            raise TrackerError("Counts must be between 0 and 50.")
    app = get(session, app_id)
    app.interviews_override, app.offers_override = interviews, offers
    app.updated_at = _now()
    return app


def delete(session: Session, app_id: int) -> None:
    session.delete(get(session, app_id))


def status_counts(session: Session) -> dict[str, int]:
    rows = session.execute(select(Application.status, func.count()).group_by(Application.status)).all()
    counts = dict.fromkeys(STATUS_NAMES, 0)
    counts.update({s: n for s, n in rows})
    return counts


def due_actions(session: Session, today: date | None = None, within_days: int = 7) -> list[Application]:
    """Active applications with a follow-up date that is overdue or within the next few days."""
    today = today or date.today()
    query = (select(Application).where(Application.status.in_(ACTIVE), Application.next_action_on.is_not(None))
             .order_by(Application.next_action_on))
    return [a for a in session.scalars(query) if (a.next_action_on - today).days <= within_days]


# --- Study progress (Interview Preparation) ---------------------------------

def study_statuses(session: Session, job_key: str) -> dict[str, str]:
    rows = session.scalars(select(StudyProgress).where(StudyProgress.job_key == job_key))
    return {r.topic_id: r.status for r in rows}


def set_study_status(session: Session, job_key: str, topic_id: str, status: str) -> None:
    row = session.scalar(select(StudyProgress).where(StudyProgress.job_key == job_key,
                                                     StudyProgress.topic_id == topic_id))
    if row is None:
        session.add(StudyProgress(job_key=job_key[:600], topic_id=topic_id[:300], status=status))
    else:
        row.status = status
