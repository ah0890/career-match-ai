"""Local filtering for providers that return a broad feed rather than searching server-side."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from src.jobs.countries import country_terms
from src.jobs.models import EmploymentType, JobPosting, SearchQuery

_IGNORED = frozenset({"and", "or", "the", "a", "an", "of", "in", "for", "with", "to", "job", "jobs", "role"})
_WORLDWIDE = ("worldwide", "anywhere", "global", "remote")


def keyword_groups(keywords: str) -> list[list[str]]:
    """'Data Analyst, Python' → [['data', 'analyst'], ['python']] (groups are alternatives)."""
    groups = []
    for part in re.split(r"[,;|]|\bOR\b", keywords):
        tokens = [t for t in re.findall(r"[a-z0-9+#.]+", part.lower()) if t not in _IGNORED and len(t) >= 2]
        if tokens:
            groups.append(tokens)
    return groups


def _contains(haystack: str, token: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", haystack) is not None


def matches_keywords(job: JobPosting, keywords: str) -> bool:
    groups = keyword_groups(keywords)
    if not groups:
        return True
    haystack = " ".join([job.title, " ".join(job.tags), job.category or "", job.description]).lower()
    return any(all(_contains(haystack, t) for t in group) for group in groups)


def matches_location(job: JobPosting, location: str | None, country: str | None = None) -> bool:
    """For remote boards: keep jobs open to the requested location/country or to anyone.

    Jobs whose location is not stated are kept (missing data is never a reason to discard).
    """
    wanted = [t.strip().lower() for t in re.split(r"[,/]", location or "") if t.strip()]
    wanted = [w for w in wanted if w not in {"remote", "anywhere", "worldwide"}] + country_terms(country)
    if not wanted:
        return True
    job_loc = (job.location or "").lower()
    if not job_loc or any(w in job_loc for w in _WORLDWIDE):
        return True
    return any(w in job_loc for w in wanted)


def apply_local_filters(jobs: list[JobPosting], query: SearchQuery, *, now: datetime | None = None) -> list[JobPosting]:
    now = now or datetime.now(timezone.utc)
    out = []
    for job in jobs:
        if not matches_keywords(job, query.keywords):
            continue
        if not matches_location(job, query.location, query.country):
            continue
        if query.employer and (not job.company or query.employer.lower() not in job.company.lower()):
            continue
        if (query.employment_type is not EmploymentType.ANY and job.employment_type is not EmploymentType.UNKNOWN
                and job.employment_type is not query.employment_type):
            continue  # jobs with an unknown type are kept rather than discarded on missing data
        if query.posted_within_days and job.posted_at and job.posted_at < now - timedelta(days=query.posted_within_days):
            continue
        out.append(job)
    return out[: query.max_results]
