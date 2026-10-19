"""Search history, stored in the local database. Only search terms and counts are kept — never CV data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from pydantic import ValidationError
from sqlalchemy import delete, select

from src.db.engine import session_scope
from src.db.models import SearchHistory
from src.jobs.countries import COUNTRIES
from src.jobs.models import EmploymentType, SearchQuery, WorkArrangement
from src.services.job_search import SearchOutcome

HISTORY_LIMIT = 50  # older entries are removed automatically


@dataclass(frozen=True)
class PastSearch:
    id: int
    query: SearchQuery
    summary: str
    total_jobs: int
    sources_ok: int
    sources_failed: int
    searched_at: datetime


def describe(q: SearchQuery) -> str:
    parts = [q.keywords]
    if q.location:
        parts.append(q.location)
    if q.country:
        parts.append(COUNTRIES.get(q.country, q.country.upper()))
    if q.work_arrangement is not WorkArrangement.ANY:
        parts.append(q.work_arrangement.value.capitalize())
    if q.employment_type is not EmploymentType.ANY:
        parts.append(q.employment_type.value.replace("_", "-"))
    if q.posted_within_days:
        parts.append(f"last {q.posted_within_days} day(s)")
    return " · ".join(parts)[:300]


def record_search(url: str, outcome: SearchOutcome) -> None:
    with session_scope(url) as s:
        s.add(SearchHistory(
            keywords=outcome.query.keywords[:200], query_json=outcome.query.model_dump_json(),
            summary=describe(outcome.query), total_jobs=len(outcome.unique_jobs),
            sources_ok=len(outcome.succeeded), sources_failed=len(outcome.failed), searched_at=outcome.searched_at,
        ))
        s.flush()
        stale = list(s.scalars(select(SearchHistory.id).order_by(SearchHistory.searched_at.desc()).offset(HISTORY_LIMIT)))
        if stale:
            s.execute(delete(SearchHistory).where(SearchHistory.id.in_(stale)))


def recent_searches(url: str, limit: int = 10) -> list[PastSearch]:
    out = []
    with session_scope(url) as s:
        rows = s.scalars(select(SearchHistory).order_by(SearchHistory.searched_at.desc()).limit(limit))
        for r in rows:
            try:
                query = SearchQuery.model_validate_json(r.query_json)
            except ValidationError:  # written by an older version; skip rather than guess
                continue
            at = r.searched_at if r.searched_at.tzinfo else r.searched_at.replace(tzinfo=timezone.utc)
            out.append(PastSearch(r.id, query, r.summary, r.total_jobs, r.sources_ok, r.sources_failed, at))
    return out


def clear_history(url: str) -> int:
    with session_scope(url) as s:
        return s.execute(delete(SearchHistory)).rowcount or 0
