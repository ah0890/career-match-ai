"""HTTP access for providers: timeouts, retries, rate limits, request budgets and caching.

Error messages never include URLs or query parameters, so credentials passed as
parameters cannot leak into the UI or logs.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Protocol

import httpx

from src.providers.base import (
    ProviderError, ProviderRateLimited, ProviderResponseError, ProviderTimeout, ProviderUnavailable,
)

USER_AGENT = "CareerMatchAI/0.1 (personal job-search assistant; https://github.com/ah0890/career-match-ai)"


@dataclass(frozen=True)
class RequestPolicy:
    min_interval_s: float = 1.0  # minimum spacing between requests to one provider
    daily_limit: int | None = None  # maximum live requests per calendar day (None = unlimited)
    cache_ttl_s: float = 3600.0  # how long a response is reused


class PersistentStore(Protocol):
    """Optional on-disk storage so caches and daily request budgets survive app restarts."""

    def get(self, key: str, max_age_s: float) -> tuple[Any, datetime] | None: ...
    def put(self, key: str, provider_id: str, payload: Any, fetched_at: datetime) -> None: ...
    def count(self, provider_id: str, day: date) -> int: ...
    def increment(self, provider_id: str, day: date) -> None: ...


@dataclass
class _CacheEntry:
    stored_at: float
    fetched_at: datetime
    payload: Any


@dataclass(frozen=True)
class JsonResponse:
    payload: Any
    from_cache: bool
    fetched_at: datetime


class ProviderHttp:
    """Shared, thread-safe HTTP helper used by all provider adapters."""

    def __init__(
        self,
        *,
        timeout_s: float = 15.0,
        retries: int = 2,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        today: Callable[[], date] = date.today,
        offline: bool = False,
        store: PersistentStore | None = None,
    ):
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout_s), transport=transport, follow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        self._retries = retries
        self._clock, self._sleep, self._today = clock, sleep, today
        self._offline = offline
        self._store = store
        self._lock = threading.Lock()
        self._cache: dict[str, _CacheEntry] = {}
        self._last_request: dict[str, float] = {}
        self._daily: dict[str, tuple[date, int]] = {}

    # --- public ---------------------------------------------------------
    def get_json(self, provider_id: str, url: str, *, params: dict[str, Any] | None = None,
                 policy: RequestPolicy = RequestPolicy(), use_cache: bool = True) -> JsonResponse:
        return self._request(provider_id, "GET", url, params=params, policy=policy, use_cache=use_cache)

    def post_json(self, provider_id: str, url: str, *, body: dict[str, Any],
                  policy: RequestPolicy = RequestPolicy(), use_cache: bool = True) -> JsonResponse:
        return self._request(provider_id, "POST", url, body=body, policy=policy, use_cache=use_cache)

    def requests_today(self, provider_id: str) -> int:
        day, count = self._daily.get(provider_id, (self._today(), 0))
        count = count if day == self._today() else 0
        return max(count, self._store.count(provider_id, self._today())) if self._store else count

    def clear_cache(self, provider_id: str | None = None) -> None:
        with self._lock:
            if provider_id is None:
                self._cache.clear()
            else:
                for key in [k for k in self._cache if k.startswith(f"{provider_id}:")]:
                    del self._cache[key]

    def close(self) -> None:
        self._client.close()

    # --- internals ------------------------------------------------------
    @staticmethod
    def _key(provider_id: str, method: str, url: str, params: Any, body: Any) -> str:
        raw = json.dumps([method, url, params or {}, body or {}], sort_keys=True, default=str)
        return f"{provider_id}:{hashlib.sha256(raw.encode()).hexdigest()}"

    def _cached(self, key: str, ttl: float) -> _CacheEntry | None:
        entry = self._cache.get(key)
        if entry and self._clock() - entry.stored_at <= ttl:
            return entry
        return None

    def _reserve(self, provider_id: str, policy: RequestPolicy) -> float:
        """Enforce the daily budget; return how long to wait to respect request spacing."""
        today = self._today()
        day, count = self._daily.get(provider_id, (today, 0))
        if day != today:
            count = 0
        if self._store is not None:  # requests made before a restart still count
            count = max(count, self._store.count(provider_id, today))
        if policy.daily_limit is not None and count >= policy.daily_limit:
            raise ProviderRateLimited(
                "The daily request limit for this source has been reached to respect its usage terms. "
                "Results already retrieved today can still be shown; try again tomorrow."
            )
        self._daily[provider_id] = (today, count + 1)
        if self._store is not None:
            self._store.increment(provider_id, today)
        now = self._clock()
        last = self._last_request.get(provider_id)
        wait = max(0.0, policy.min_interval_s - (now - last)) if last is not None else 0.0
        self._last_request[provider_id] = now + wait
        return wait

    def _request(self, provider_id: str, method: str, url: str, *, params=None, body=None,
                 policy: RequestPolicy, use_cache: bool) -> JsonResponse:
        key = self._key(provider_id, method, url, params, body)
        with self._lock:
            if use_cache and (hit := self._cached(key, policy.cache_ttl_s)):
                return JsonResponse(hit.payload, True, hit.fetched_at)
            if use_cache and self._store is not None and (stored := self._store.get(key, policy.cache_ttl_s)):
                payload, fetched_at = stored
                self._cache[key] = _CacheEntry(self._clock(), fetched_at, payload)
                return JsonResponse(payload, True, fetched_at)
            if self._offline:
                raise ProviderUnavailable("Offline mode is enabled, so no external requests are made.")
            wait = self._reserve(provider_id, policy)
        if wait:
            self._sleep(wait)  # outside the lock so other providers are not blocked

        payload = self._send_with_retries(method, url, params, body)
        fetched_at = datetime.now(timezone.utc)
        with self._lock:
            self._cache[key] = _CacheEntry(self._clock(), fetched_at, payload)
            if self._store is not None:
                self._store.put(key, provider_id, payload, fetched_at)
        return JsonResponse(payload, False, fetched_at)

    def _send_with_retries(self, method: str, url: str, params, body) -> Any:
        last_error: ProviderError | None = None
        for attempt in range(self._retries + 1):
            if attempt:
                self._sleep(min(4.0, 0.5 * 2 ** (attempt - 1)))
            try:
                response = self._client.request(method, url, params=params, json=body)
            except httpx.TimeoutException:
                last_error = ProviderTimeout("The source did not respond in time.")
                continue
            except httpx.TransportError:
                last_error = ProviderUnavailable("The source could not be reached. Check your internet connection.")
                continue

            status = response.status_code
            if status == 429:
                last_error = ProviderRateLimited("The source is limiting requests right now. Try again later.")
                continue
            if status >= 500:
                last_error = ProviderUnavailable(f"The source is temporarily unavailable (HTTP {status}).")
                continue
            if status in (401, 403):
                raise ProviderError(f"The source refused access (HTTP {status}). Check the credentials in Settings.")
            if status >= 400:
                raise ProviderResponseError(f"The source rejected the request (HTTP {status}).")
            try:
                return response.json()
            except ValueError as exc:
                raise ProviderResponseError("The source returned data in an unexpected format.") from exc
        assert last_error is not None
        raise last_error
