"""Per-account operations behind the API, built on the same engines as the Streamlit app.

Every query is scoped by ``user_id``: a job id that belongs to someone else behaves exactly
like one that does not exist.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from config.settings import Settings
from src.api.models import User, UserCV, UserJob
from src.cv.extraction import ExtractionResult
from src.cv.session import ActiveCV
from src.jobs.models import JobPosting, safe_url
from src.jobs.normalization import clean_text
from src.matching.engine import MatchProfile, MatchResult, build_profile, match_job
from src.matching.recommendations import Recommendation, recommend

USER_PROVIDER = "user"  # provider id for jobs the user submitted (extension or pasted text)


class NotFound(LookupError):
    pass


@dataclass(frozen=True)
class JobInput:
    title: str
    description: str
    company: str | None = None
    location: str | None = None
    url: str | None = None
    apply_url: str | None = None
    source_name: str | None = None


# --- CV -------------------------------------------------------------------

def get_cv(session: Session, user: User) -> UserCV | None:
    return session.scalar(select(UserCV).where(UserCV.user_id == user.id))


def store_cv(session: Session, user: User, cv: ActiveCV) -> UserCV:
    row = get_cv(session, user) or UserCV(user_id=user.id)
    row.filename, row.kind, row.page_count = cv.filename, cv.extraction.kind, cv.extraction.page_count
    row.sha256, row.text, row.uploaded_at = cv.sha256, cv.extraction.text, cv.uploaded_at
    session.add(row)
    session.flush()
    return row


def delete_cv(session: Session, user: User) -> bool:
    row = get_cv(session, user)
    if row is None:
        return False
    session.delete(row)
    return True


def profile_for(row: UserCV) -> MatchProfile:
    return build_profile(ExtractionResult(row.text, row.kind, row.page_count))  # type: ignore[arg-type]


# --- Jobs -----------------------------------------------------------------

def _source_name(job: JobInput, url: str | None) -> str:
    if job.source_name and job.source_name.strip():
        return clean_text(job.source_name, 100) or "Added by you"
    host = urlsplit(url).hostname if url else None
    return (host.removeprefix("www.") if host else "Added by you")[:100]


def job_key_for(job: JobInput, url: str | None) -> str:
    basis = url or "|".join([job.title.strip().lower(), (job.company or "").strip().lower(),
                             " ".join(job.description.split())[:500]])
    return f"{USER_PROVIDER}:{hashlib.sha256(basis.encode()).hexdigest()[:32]}"


def posting(row: UserJob) -> JobPosting:
    return JobPosting(provider_id=USER_PROVIDER, source_name=row.source_name, source_job_id=row.job_key,
                      title=row.title, company=row.company, location=row.location, description=row.description,
                      listing_url=row.listing_url, apply_url=row.apply_url)


def upsert_job(session: Session, user: User, job: JobInput) -> UserJob:
    """Save the job for this user; analysing the same listing again updates it instead of duplicating it."""
    url = safe_url(job.url)
    key = job_key_for(job, url)
    row = session.scalar(select(UserJob).where(UserJob.user_id == user.id, UserJob.job_key == key))
    if row is None:
        row = UserJob(user_id=user.id, job_key=key)
    row.title = clean_text(job.title, 300) or "Untitled job"
    row.company = clean_text(job.company, 300)
    row.location = clean_text(job.location, 300)
    row.source_name = _source_name(job, url)
    row.listing_url = url
    row.apply_url = safe_url(job.apply_url)
    row.description = job.description.strip()
    session.add(row)
    session.flush()
    return row


def get_job(session: Session, user: User, job_id: int) -> UserJob:
    row = session.scalar(select(UserJob).where(UserJob.id == job_id, UserJob.user_id == user.id))
    if row is None:
        raise NotFound("Job not found.")
    return row


def list_jobs(session: Session, user: User) -> list[UserJob]:
    return list(session.scalars(select(UserJob).where(UserJob.user_id == user.id)
                                .order_by(UserJob.updated_at.desc(), UserJob.id.desc())))


def delete_job(session: Session, user: User, job_id: int) -> None:
    session.delete(get_job(session, user, job_id))


def analyse(profile: MatchProfile, row: UserJob, settings: Settings) -> tuple[MatchResult, Recommendation]:
    result = match_job(profile, posting(row), settings.scoring_weights)
    rec = recommend(result, settings.thresholds)
    row.match_score = float(result.score)
    row.recommendation = rec.label.value
    return result, rec


def download_name(row: UserJob) -> str:
    """A safe file name such as ``cv-senior-quality-engineer-example-devices``."""
    slug = re.sub(r"[^a-z0-9]+", "-", f"cv {row.title} {row.company or ''}".lower()).strip("-")
    return slug[:80] or "cv"
