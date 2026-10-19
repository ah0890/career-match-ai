"""Rank the current search results against the active CV, cached per session.

Matching runs locally; no CV or job data leaves the computer.
"""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

from config.settings import ScoringWeights
from src.cv.session import ActiveCV
from src.matching.engine import MatchResult, build_profile, rank_jobs
from src.services.job_search import SearchOutcome

_CACHE_KEY = "cm_match_cache"


def ranked_matches(state: MutableMapping[str, Any], cv: ActiveCV, outcome: SearchOutcome,
                   weights: ScoringWeights) -> list[MatchResult]:
    """Matches for the latest search; recomputed only when the CV, search or weights change."""
    key = (cv.sha256, outcome.searched_at, tuple(weights.as_dict().items()))
    cached = state.get(_CACHE_KEY)
    if cached and cached[0] == key:
        return cached[1]
    results = rank_jobs(build_profile(cv.extraction), list(outcome.unique_jobs), weights)
    state[_CACHE_KEY] = (key, results)
    return results


def clear_matches(state: MutableMapping[str, Any]) -> None:
    state.pop(_CACHE_KEY, None)
