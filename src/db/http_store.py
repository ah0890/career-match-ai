"""SQLite-backed storage for job-source responses and daily request counts."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import delete, func, select

from src.db.engine import session_scope
from src.db.models import HttpCacheEntry, RequestCount


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)  # SQLite drops the timezone


class SqlHttpStore:
    """Implements ``PersistentStore`` for ``ProviderHttp``. Failures never break a search."""

    def __init__(self, url: str, now=lambda: datetime.now(timezone.utc)):
        self._url = url
        self._now = now

    def get(self, key: str, max_age_s: float) -> tuple[Any, datetime] | None:
        try:
            with session_scope(self._url) as s:
                row = s.get(HttpCacheEntry, key)
                if row is None:
                    return None
                fetched = _aware(row.fetched_at)
                if (self._now() - fetched).total_seconds() > max_age_s:
                    return None
                return json.loads(row.payload), fetched
        except Exception:  # a damaged cache must never stop a search
            return None

    def put(self, key: str, provider_id: str, payload: Any, fetched_at: datetime) -> None:
        try:
            text = json.dumps(payload)
            with session_scope(self._url) as s:
                s.merge(HttpCacheEntry(key=key, provider_id=provider_id, payload=text, fetched_at=fetched_at))
        except Exception:
            pass

    def count(self, provider_id: str, day: date) -> int:
        try:
            with session_scope(self._url) as s:
                row = s.get(RequestCount, (provider_id, day))
                return row.count if row else 0
        except Exception:
            return 0

    def increment(self, provider_id: str, day: date) -> None:
        try:
            with session_scope(self._url) as s:
                row = s.get(RequestCount, (provider_id, day))
                if row is None:
                    s.add(RequestCount(provider_id=provider_id, day=day, count=1))
                else:
                    row.count += 1
        except Exception:
            pass


def cache_stats(url: str) -> tuple[int, datetime | None]:
    """(number of cached responses, oldest fetch time)."""
    with session_scope(url) as s:
        n, oldest = s.execute(select(func.count(), func.min(HttpCacheEntry.fetched_at))).one()
        return n, _aware(oldest) if oldest else None


def clear_cache(url: str) -> int:
    """Delete cached responses (request counts are kept so daily limits still apply)."""
    with session_scope(url) as s:
        return s.execute(delete(HttpCacheEntry)).rowcount or 0
