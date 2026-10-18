"""Search all usable providers independently and collect their results.

One provider failing never prevents results from the others being shown.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone

from config.settings import Settings
from src.jobs.deduplication import deduplicate
from src.jobs.models import JobPosting, SearchQuery
from src.providers.base import JobProvider, ProviderError, ProviderResult
from src.providers.http import ProviderHttp
from src.providers.registry import ProviderStatus, build_providers, provider_status


@dataclass(frozen=True)
class SearchOutcome:
    query: SearchQuery
    results: tuple[ProviderResult, ...]
    searched_at: datetime
    unique_jobs: tuple[JobPosting, ...] = field(default=())
    duplicates_merged: int = 0

    @property
    def jobs(self) -> list[JobPosting]:
        """Every posting as returned by the sources (before duplicates are merged)."""
        return [job for r in self.results for job in r.jobs]

    @property
    def succeeded(self) -> list[ProviderResult]:
        return [r for r in self.results if r.status == "ok"]

    @property
    def failed(self) -> list[ProviderResult]:
        return [r for r in self.results if r.status == "error"]

    @property
    def skipped(self) -> list[ProviderResult]:
        return [r for r in self.results if r.status == "skipped"]


def _run_one(provider: JobProvider, query: SearchQuery, http: ProviderHttp) -> ProviderResult:
    info = provider.info
    reason = provider.unsupported_reason(query)
    if reason:
        return ProviderResult(info.id, info.name, "skipped", message=reason)
    start = time.perf_counter()
    try:
        page = provider.search(query, http)
    except ProviderError as exc:
        return ProviderResult(info.id, info.name, "error", message=exc.message, retryable=exc.retryable,
                              duration_ms=int((time.perf_counter() - start) * 1000))
    except Exception:  # an adapter bug must not break the whole search
        return ProviderResult(info.id, info.name, "error",
                              message="An unexpected error occurred while reading this source.",
                              duration_ms=int((time.perf_counter() - start) * 1000))
    # Cached responses are reported as such so users know results may be older.
    return ProviderResult(info.id, info.name, "ok", jobs=tuple(page.jobs), from_cache=page.from_cache,
                          fetched_at=page.fetched_at, duration_ms=int((time.perf_counter() - start) * 1000))


def search_jobs(query: SearchQuery, settings: Settings, http: ProviderHttp,
                providers: list[JobProvider] | None = None) -> SearchOutcome:
    providers = providers if providers is not None else build_providers(settings)
    usable: list[JobProvider] = []
    results: list[ProviderResult] = []
    for provider in providers:
        status: ProviderStatus = provider_status(provider)
        if status.usable:
            usable.append(provider)
        elif status.availability in ("needs_configuration", "offline"):
            results.append(ProviderResult(provider.info.id, provider.info.name, "skipped", message=status.detail))
    if usable:
        with ThreadPoolExecutor(max_workers=min(8, len(usable))) as pool:
            results.extend(pool.map(lambda p: _run_one(p, query, http), usable))
    all_jobs = [job for r in results for job in r.jobs]
    dedup = deduplicate(all_jobs)
    return SearchOutcome(query, tuple(results), datetime.now(timezone.utc), tuple(dedup.jobs), dedup.duplicates_merged)
