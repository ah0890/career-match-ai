"""Registry of job-search providers, plus sources that were evaluated but cannot be supported."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from config.settings import Settings
from src.providers.adapters.himalayas import HimalayasProvider
from src.providers.adapters.jobicy import JobicyProvider
from src.providers.adapters.remoteok import RemoteOKProvider
from src.providers.adapters.remotive import RemotiveProvider
from src.providers.base import JobProvider

PROVIDER_CLASSES: tuple[type[JobProvider], ...] = (
    HimalayasProvider, JobicyProvider, RemoteOKProvider, RemotiveProvider,
)

Availability = Literal["ready", "needs_configuration", "disabled", "offline"]


@dataclass(frozen=True)
class ProviderStatus:
    provider: JobProvider
    availability: Availability
    detail: str

    @property
    def usable(self) -> bool:
        return self.availability == "ready"


def build_providers(settings: Settings) -> list[JobProvider]:
    return [cls(settings) for cls in PROVIDER_CLASSES]


def provider_status(provider: JobProvider) -> ProviderStatus:
    settings = provider.settings
    if settings.offline_mode:
        return ProviderStatus(provider, "offline", "Offline mode is on, so no external requests are made.")
    if not provider.is_enabled():
        return ProviderStatus(provider, "disabled", "Disabled in configuration.")
    missing = provider.missing_configuration()
    if missing:
        return ProviderStatus(provider, "needs_configuration", "Set " + ", ".join(missing) + " to enable.")
    return ProviderStatus(provider, "ready", provider.info.access)


def statuses(settings: Settings) -> list[ProviderStatus]:
    return [provider_status(p) for p in build_providers(settings)]


@dataclass(frozen=True)
class UnsupportedSource:
    name: str
    reason: str


# Sources users commonly expect. None offers a public job-search API that this app may use, and
# automated scraping would breach their terms or bypass access controls, so they are not integrated.
UNSUPPORTED_SOURCES: tuple[UnsupportedSource, ...] = (
    UnsupportedSource("LinkedIn Jobs", "No public job-search API; access is restricted to approved partners."),
    UnsupportedSource("Indeed", "No public job-search API for third-party applications."),
    UnsupportedSource("Glassdoor", "No public job-search API."),
    UnsupportedSource("Google Jobs", "No official public API; only third-party paid scraping services exist."),
    UnsupportedSource("Bayt", "No public job-search API."),
    UnsupportedSource("GulfTalent", "No public job-search API."),
    UnsupportedSource("Naukrigulf", "No public job-search API."),
    UnsupportedSource("Rozee.pk", "No public job-search API."),
    UnsupportedSource("Mustakbil", "No public job-search API."),
    UnsupportedSource("Wellfound", "No public job-search API."),
    UnsupportedSource("Arbeitnow", "Public endpoint exists, but its terms of use could not be verified."),
    UnsupportedSource("Jooble", "Requires a key; official API documentation could not be verified."),
    UnsupportedSource("Adzuna", "Removed: its API needs paid access; only free sources are used."),
)
