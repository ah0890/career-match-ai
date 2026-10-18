"""Evidence-based freshness labels.

A label is assigned only from evidence the source provided (posting or expiry date).
A job is never described as "open" merely because its listing URL exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from src.jobs.models import JobPosting

RECENT_DAYS = 7
OLDER_DAYS = 30


class Freshness(str, Enum):
    RECENT = "recent"
    OLDER = "older"
    POSSIBLY_STALE = "possibly_stale"
    EXPIRED = "expired"
    UNVERIFIED = "unverified"


@dataclass(frozen=True)
class FreshnessInfo:
    status: Freshness
    label: str
    tone: str
    explanation: str


def assess(job: JobPosting, now: datetime | None = None) -> FreshnessInfo:
    now = now or datetime.now(timezone.utc)
    caveat = "Availability is not confirmed — check the original listing before applying."
    if job.expires_at and job.expires_at < now:
        return FreshnessInfo(Freshness.EXPIRED, "Expired", "danger",
                             f"The source lists this job as expiring on {job.expires_at:%d %b %Y}.")
    if job.posted_at is None:
        return FreshnessInfo(Freshness.UNVERIFIED, "Date not provided", "neutral",
                             f"The source did not provide a posting date. {caveat}")
    age = (now - job.posted_at).days
    if age <= RECENT_DAYS:
        return FreshnessInfo(Freshness.RECENT, "Recent", "success", f"Posted {max(age, 0)} day(s) ago. {caveat}")
    if age <= OLDER_DAYS:
        return FreshnessInfo(Freshness.OLDER, "Older", "info", f"Posted {age} days ago. {caveat}")
    return FreshnessInfo(Freshness.POSSIBLY_STALE, "Possibly stale", "warning",
                         f"Posted {age} days ago; it may already be filled. {caveat}")
