"""Application tracker operations. Only the user changes a status — opening a link never does."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from src.db.models import Application, StatusChange, StudyProgress
from src.jobs.models import JobPosting, safe_url
from src.matching.recommendations import RankedMatch

STATUSES: tuple[tuple[str, str, str], ...] = (
    ("Saved", "neutral", "Kept for later review."),
    ("To Apply", "info", "You intend to apply."),
    ("Applied", "info", "You confirmed you submitted an application."),
    ("Interview", "warning", "An interview is scheduled or in progress."),
    ("Offer", "success", "You received an offer."),
    ("Rejected", "danger", "The application was unsuccessful."),
    ("Withdrawn", "neutral", "You withdrew from the process."),
)
STATUS_NAMES = tuple(s for s, _, _ in STATUSES)
STATUS_TONES = {s: tone for s, tone, _ in STATUSES}
ACTIVE = ("Saved", "To Apply", "Applied", "Interview")


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


def _clean(text: str | None, limit: int) -> str | None:
    text = " ".join((text or "").split())
    return text[:limit] or None


def _check_status(status: str) -> str:
    if status not in STATUS_NAMES:
        raise TrackerError(f"Unknown status: {status}.")
    return status


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
    session.add(app)
    session.flush()
    return app, True


def add_manual(session: Session, data: ApplicationInput) -> Application:
    title = _clean(data.title, 300)
    if not title or len(title) < 2:
        raise TrackerError("Enter a job title of at least 2 characters.")
    if data.listing_url and not safe_url(data.listing_url):
        raise TrackerError("The link must be a full http(s) address, e.g. https://example.com/job.")
    app = Application(title=title, company=_clean(data.company, 300), location=_clean(data.location, 300),
                      source_name="Added manually", listing_url=safe_url(data.listing_url),
                      status=_check_status(data.status), notes=(data.notes or "").strip()[:5000] or None)
    app.history.append(StatusChange(from_status=None, to_status=app.status))
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


def set_status(session: Session, app_id: int, status: str, today: date | None = None) -> Application:
    app = get(session, app_id)
    status = _check_status(status)
    if status == app.status:
        return app
    app.history.append(StatusChange(from_status=app.status, to_status=status))
    app.status = status
    if status == "Applied" and app.applied_on is None:
        app.applied_on = today or date.today()
    app.updated_at = datetime.now(timezone.utc)
    return app


def update_details(session: Session, app_id: int, *, notes: str | None, next_action: str | None,
                   next_action_on: date | None, applied_on: date | None) -> Application:
    app = get(session, app_id)
    app.notes = (notes or "").strip()[:5000] or None
    app.next_action = _clean(next_action, 300)
    app.next_action_on = next_action_on
    app.applied_on = applied_on
    app.updated_at = datetime.now(timezone.utc)
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
