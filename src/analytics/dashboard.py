"""Dashboard figures computed only from the user's real data (database and current session)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import Application, SearchHistory
from src.matching.recommendations import Label, RankedMatch
from src.tracker.repository import ACTIVE, STATUS_NAMES, status_counts


@dataclass(frozen=True)
class WeekCount:
    week_start: date  # Monday
    count: int


@dataclass(frozen=True)
class ActivitySummary:
    searches_30d: int
    status_counts: dict[str, int]
    applied_per_week: tuple[WeekCount, ...]

    @property
    def tracked(self) -> int:
        return sum(self.status_counts.values())

    @property
    def active(self) -> int:
        return sum(self.status_counts[s] for s in ACTIVE)

    @property
    def has_activity(self) -> bool:
        return bool(self.searches_30d or self.tracked)


@dataclass(frozen=True)
class MatchSummary:
    total: int
    by_label: dict[Label, int]
    scores: tuple[int, ...]  # reliable (not low-confidence) scores only
    top: tuple[RankedMatch, ...]


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def weekly_applications(session: Session, today: date | None = None, weeks: int = 12) -> tuple[WeekCount, ...]:
    """How many applications were submitted in each of the last ``weeks`` weeks (oldest first)."""
    today = today or date.today()
    first = _monday(today) - timedelta(weeks=weeks - 1)
    counts = {first + timedelta(weeks=i): 0 for i in range(weeks)}
    rows = session.scalars(select(Application.applied_on).where(Application.applied_on >= first))
    for applied_on in rows:
        week = _monday(applied_on)
        if week in counts:
            counts[week] += 1
    return tuple(WeekCount(w, n) for w, n in counts.items())


def activity_summary(session: Session, today: date | None = None) -> ActivitySummary:
    today = today or date.today()
    since = datetime.combine(today - timedelta(days=30), datetime.min.time(), tzinfo=timezone.utc)
    searches = len(list(session.scalars(select(SearchHistory.id).where(SearchHistory.searched_at >= since))))
    return ActivitySummary(searches, status_counts(session), weekly_applications(session, today))


def match_summary(ranked: list[RankedMatch], top_n: int = 3) -> MatchSummary:
    by_label = {label: sum(m.recommendation.label is label for m in ranked) for label in Label}
    reliable = [m for m in ranked if m.result.confidence != "Low"]
    top = tuple(m for m in reliable if m.recommendation.label is Label.APPLY)[:top_n]
    return MatchSummary(len(ranked), by_label, tuple(m.result.score for m in reliable), top)


def pipeline(counts: dict[str, int]) -> list[tuple[str, int]]:
    """Statuses in process order, only those with at least one application."""
    return [(s, counts[s]) for s in STATUS_NAMES if counts.get(s)]
