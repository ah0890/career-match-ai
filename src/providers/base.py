"""Provider interface, metadata and error types."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from config.settings import Settings
from src.jobs.models import JobPosting, SearchQuery

Filter = Literal["keywords", "location", "country", "work_arrangement", "employment_type",
                 "posted_within_days", "salary_min", "employer"]


@dataclass(frozen=True)
class ProviderInfo:
    id: str
    name: str
    website: str
    description: str
    coverage: str
    access: str  # how access is authorised, e.g. "Public API (no key)"
    terms_url: str
    attribution: str  # shown with every result from this provider
    supported_filters: frozenset[str]
    credential_env_vars: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


class ProviderError(Exception):
    """A provider failed. ``message`` is safe to show to the user."""

    retryable: bool = False

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class ProviderNotConfigured(ProviderError):
    pass


class ProviderTimeout(ProviderError):
    retryable = True


class ProviderRateLimited(ProviderError):
    retryable = True


class ProviderUnavailable(ProviderError):
    retryable = True


class ProviderResponseError(ProviderError):
    """The provider answered with something we could not understand."""


class ProviderUnsupportedQuery(ProviderError):
    """The provider cannot answer this kind of query (e.g. on-site jobs from a remote-only board)."""


@dataclass(frozen=True)
class SearchPage:
    """What an adapter returns: the jobs plus whether they came from a cached response."""

    jobs: list[JobPosting]
    from_cache: bool = False
    fetched_at: datetime | None = None


Status = Literal["ok", "error", "skipped"]


@dataclass(frozen=True)
class ProviderResult:
    provider_id: str
    provider_name: str
    status: Status
    jobs: tuple[JobPosting, ...] = ()
    message: str | None = None
    retryable: bool = False
    from_cache: bool = False
    fetched_at: datetime | None = None
    duration_ms: int = 0
    notes: tuple[str, ...] = field(default_factory=tuple)


class JobProvider(ABC):
    info: ProviderInfo

    def __init__(self, settings: Settings):
        self.settings = settings

    def is_enabled(self) -> bool:
        return True

    def missing_configuration(self) -> list[str]:
        """Names of required settings that are not set (empty when ready to use)."""
        return []

    @property
    def is_configured(self) -> bool:
        return not self.missing_configuration()

    def unsupported_reason(self, query: SearchQuery) -> str | None:
        """Explain why this provider cannot serve the query, or None if it can."""
        return None

    @abstractmethod
    def search(self, query: SearchQuery, http) -> SearchPage:
        """Run the search. Raise a ProviderError subclass on failure."""
