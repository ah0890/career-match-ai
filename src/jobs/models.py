"""Shared job-search data models.

Every provider adapter converts its own response format into ``JobPosting`` so the
rest of the application never depends on a particular provider.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


class WorkArrangement(str, Enum):
    ANY = "any"
    REMOTE = "remote"
    HYBRID = "hybrid"
    ONSITE = "onsite"
    UNKNOWN = "unknown"


class EmploymentType(str, Enum):
    ANY = "any"
    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    CONTRACT = "contract"
    TEMPORARY = "temporary"
    INTERNSHIP = "internship"
    UNKNOWN = "unknown"


def safe_url(value: object) -> str | None:
    """Return the URL if it is an absolute http(s) URL with a host; otherwise None."""
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not candidate or any(ch.isspace() for ch in candidate) or len(candidate) > 2048:
        return None
    try:
        parts = urlsplit(candidate)
    except ValueError:
        return None
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname or "." not in parts.hostname:
        return None
    if parts.username or parts.password:  # credentials embedded in URLs are a phishing pattern
        return None
    return candidate


class SearchQuery(BaseModel):
    """What the user is looking for. Providers apply the filters they support."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    keywords: str = Field(min_length=2, max_length=200)
    location: str | None = Field(default=None, max_length=120)
    country: str | None = Field(default=None, pattern=r"^[a-z]{2}$")  # ISO 3166-1 alpha-2, lowercase
    work_arrangement: WorkArrangement = WorkArrangement.ANY
    employment_type: EmploymentType = EmploymentType.ANY
    experience_level: str | None = None
    posted_within_days: int | None = Field(default=None, ge=1, le=365)
    salary_min: int | None = Field(default=None, ge=0)
    required_skills: tuple[str, ...] = ()
    preferred_skills: tuple[str, ...] = ()
    industry: str | None = None
    employer: str | None = None
    max_results: int = Field(default=50, ge=1, le=200)

    @field_validator("location", "industry", "employer", "experience_level")
    @classmethod
    def _blank_to_none(cls, v: str | None) -> str | None:
        return v or None

    def cache_key(self) -> str:
        return self.model_dump_json()


class JobPosting(BaseModel):
    """A job as returned by a provider, normalised. Unknown fields stay None — never guessed."""

    model_config = ConfigDict(frozen=True)

    provider_id: str
    source_name: str
    source_job_id: str | None = None
    title: str
    company: str | None = None
    location: str | None = None
    country: str | None = None
    work_arrangement: WorkArrangement = WorkArrangement.UNKNOWN
    employment_type: EmploymentType = EmploymentType.UNKNOWN
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = None
    salary_text: str | None = None  # provider's free-text salary when not structured
    salary_is_estimate: bool = False
    posted_at: datetime | None = None
    description: str = ""
    tags: tuple[str, ...] = ()
    category: str | None = None
    listing_url: str | None = None  # the original listing on the source site
    apply_url: str | None = None  # only when the provider supplies an explicit application link
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("listing_url", "apply_url", mode="before")
    @classmethod
    def _validate_url(cls, v: object) -> str | None:
        return safe_url(v)

    @field_validator("title")
    @classmethod
    def _title_required(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("A job must have a title.")
        return v
