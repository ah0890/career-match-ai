"""Filtering, sorting and comparison of ranked matches (pure functions, no UI)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

from src.jobs.freshness import Freshness, assess
from src.jobs.models import WorkArrangement
from src.matching.recommendations import LABEL_ORDER, Label, RankedMatch

SortKey = Literal["recommended", "score", "newest"]
SORT_LABELS: dict[SortKey, str] = {"recommended": "Recommended first", "score": "Highest score",
                                   "newest": "Most recently posted"}
COMPARE_LIMIT = 3


@dataclass(frozen=True)
class MatchFilter:
    labels: frozenset[Label] = frozenset(Label)
    min_score: int = 0
    include_low_confidence: bool = True
    hide_expired: bool = True
    sources: frozenset[str] = frozenset()  # empty = every source
    arrangements: frozenset[WorkArrangement] = frozenset()  # empty = any arrangement
    essential_gaps_ok: bool = True  # False = only jobs with no essential requirement missing
    now: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def accepts(self, m: RankedMatch) -> bool:
        r, rec = m.result, m.recommendation
        if rec.label not in self.labels or r.score < self.min_score:
            return False
        if not self.include_low_confidence and r.confidence == "Low":
            return False
        if self.hide_expired and assess(r.job, self.now).status is Freshness.EXPIRED:
            return False
        if self.sources and r.job.source_name not in self.sources:
            return False
        if self.arrangements and r.job.work_arrangement not in self.arrangements:
            return False
        return self.essential_gaps_ok or not r.mandatory_gaps


def filter_matches(matches: list[RankedMatch], criteria: MatchFilter) -> list[RankedMatch]:
    return [m for m in matches if criteria.accepts(m)]


_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def sort_matches(matches: list[RankedMatch], key: SortKey) -> list[RankedMatch]:
    """Low-confidence matches always stay after the others, whatever the sort order."""
    if key == "score":
        return sorted(matches, key=lambda m: (m.result.confidence == "Low", -m.result.score))
    if key == "newest":
        # Jobs without a posting date go last: their age is unknown, not new.
        return sorted(matches, key=lambda m: (m.result.confidence == "Low", m.result.job.posted_at is None,
                                              -(m.result.job.posted_at or _EPOCH).timestamp()))
    return sorted(matches, key=lambda m: (m.result.confidence == "Low", LABEL_ORDER[m.recommendation.label],
                                          -m.result.score))


def page_slice(matches: list[RankedMatch], page: int, per_page: int) -> tuple[list[RankedMatch], int]:
    """One page of matches and the total number of pages (at least 1). Out-of-range pages are clamped."""
    pages = max(1, -(-len(matches) // per_page))
    page = min(max(page, 1), pages)
    start = (page - 1) * per_page
    return matches[start:start + per_page], pages


def source_names(matches: list[RankedMatch]) -> list[str]:
    return sorted({m.result.job.source_name for m in matches})
