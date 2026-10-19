"""Rank the current search results against the active CV, cached per session.

Matching runs locally; no CV or job data leaves the computer.
"""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

from config.settings import ScoringWeights
from src.cv.session import ActiveCV
from src.matching.engine import MatchProfile, MatchResult, build_profile, rank_jobs
from src.services.job_search import SearchOutcome

_CACHE_KEY = "cm_match_cache"
_PROFILE_KEY = "cm_match_profile"


def match_profile(state: MutableMapping[str, Any], cv: ActiveCV) -> MatchProfile:
    """The parsed CV used for matching; rebuilt only when a different CV is active."""
    cached = state.get(_PROFILE_KEY)
    if cached and cached[0] == cv.sha256:
        return cached[1]
    profile = build_profile(cv.extraction)
    state[_PROFILE_KEY] = (cv.sha256, profile)
    return profile


def ranked_matches(state: MutableMapping[str, Any], cv: ActiveCV, outcome: SearchOutcome,
                   weights: ScoringWeights) -> list[MatchResult]:
    """Matches for the latest search; recomputed only when the CV, search or weights change."""
    key = (cv.sha256, outcome.searched_at, tuple(weights.as_dict().items()))
    cached = state.get(_CACHE_KEY)
    if cached and cached[0] == key:
        return cached[1]
    results = rank_jobs(match_profile(state, cv), list(outcome.unique_jobs), weights)
    state[_CACHE_KEY] = (key, results)
    return results


def clear_matches(state: MutableMapping[str, Any]) -> None:
    """Forget everything derived from the CV (called when the CV is deleted)."""
    state.pop(_CACHE_KEY, None)
    state.pop(_PROFILE_KEY, None)
