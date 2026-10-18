"""Cross-source duplicate detection.

Two postings are treated as the same vacancy only on strong evidence:
- the same canonical listing URL or the same source identifier; or
- the same company, near-identical titles (seniority words must match), compatible
  locations and — when both have substantial descriptions — similar descriptions.

Similar-but-different roles ("Senior Data Analyst" vs "Data Analyst") are never merged.
Every source that listed a merged vacancy is preserved in ``also_listed_on``.
"""

from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz

from src.jobs.models import JobPosting, SourceLink
from src.jobs.normalization import canonical_url, normalize_company, normalize_title

TITLE_THRESHOLD = 95
DESCRIPTION_THRESHOLD = 60
_SENIORITY = frozenset({"junior", "senior", "lead", "principal", "staff", "head", "chief", "director", "manager",
                        "intern", "graduate", "associate", "i", "ii", "iii", "iv"})


def _seniority(title: str) -> frozenset[str]:
    return frozenset(w for w in title.split() if w in _SENIORITY)


def _locations_compatible(a: JobPosting, b: JobPosting) -> bool:
    if not a.location or not b.location:
        return True  # missing location is not evidence of a different job
    la, lb = a.location.lower(), b.location.lower()
    return fuzz.token_set_ratio(la, lb) >= 80 or la in lb or lb in la


def is_duplicate(a: JobPosting, b: JobPosting) -> bool:
    if a.provider_id == b.provider_id and a.source_job_id and a.source_job_id == b.source_job_id:
        return True
    ua, ub = canonical_url(a.listing_url), canonical_url(b.listing_url)
    if ua and ub and ua == ub:
        return True
    ca, cb = normalize_company(a.company), normalize_company(b.company)
    if not ca or ca != cb:
        return False
    ta, tb = normalize_title(a.title), normalize_title(b.title)
    if _seniority(ta) != _seniority(tb) or fuzz.ratio(ta, tb) < TITLE_THRESHOLD:
        return False
    if not _locations_compatible(a, b):
        return False
    if len(a.description) >= 200 and len(b.description) >= 200:
        return fuzz.token_set_ratio(a.description[:3000], b.description[:3000]) >= DESCRIPTION_THRESHOLD
    return True


def _richness(job: JobPosting) -> tuple:
    """Prefer the posting with the most complete information as the primary record."""
    return (
        bool(job.apply_url), len(job.description) >= 500, job.salary_min is not None or job.salary_max is not None,
        job.posted_at is not None, len(job.description),
    )


@dataclass(frozen=True)
class DedupResult:
    jobs: list[JobPosting]
    duplicates_merged: int


def deduplicate(jobs: list[JobPosting]) -> DedupResult:
    groups: list[list[JobPosting]] = []
    for job in jobs:
        for group in groups:
            if any(is_duplicate(job, other) for other in group):
                group.append(job)
                break
        else:
            groups.append([job])

    merged: list[JobPosting] = []
    for group in groups:
        primary = max(group, key=_richness)
        others = [
            SourceLink(provider_id=j.provider_id, source_name=j.source_name, listing_url=j.listing_url,
                       source_url=j.source_url)
            for j in group if j is not primary
        ]
        # Keep one link per source, and only sources other than the primary's.
        seen = {primary.provider_id}
        unique_others = []
        for link in others:
            if link.provider_id not in seen:
                seen.add(link.provider_id)
                unique_others.append(link)
        posted = [j.posted_at for j in group if j.posted_at]
        update: dict = {"also_listed_on": tuple(unique_others)}
        if posted and primary.posted_at is None:
            update["posted_at"] = min(posted)  # a date reported by another source for the same vacancy
        merged.append(primary.model_copy(update=update) if update else primary)
    return DedupResult(merged, len(jobs) - len(merged))
