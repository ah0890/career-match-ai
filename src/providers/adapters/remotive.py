"""Remotive public remote-jobs API.

Docs and terms: https://github.com/remotive-io/remote-jobs-api
- Results must link back to Remotive and name Remotive as the source.
- Requests should be infrequent (about 4 per day); more than 2 per minute are blocked.
- Listings are delayed by 24 hours.

Remotive's unfiltered feed only contains a small recent sample, so searches use the
server-side ``search`` parameter. Each distinct search costs one request; identical
searches are served from cache, and a daily budget keeps usage within the terms.
"""

from __future__ import annotations

from typing import Any

from src.jobs.filtering import apply_local_filters, keyword_groups
from src.jobs.models import JobPosting, SearchQuery, WorkArrangement
from src.jobs.normalization import clean_text, html_to_text, parse_datetime, parse_employment_type
from src.providers.base import JobProvider, ProviderInfo, ProviderResponseError, SearchPage
from src.providers.http import ProviderHttp, RequestPolicy

API_URL = "https://remotive.com/api/remote-jobs"


class RemotiveProvider(JobProvider):
    info = ProviderInfo(
        id="remotive",
        name="Remotive",
        website="https://remotive.com",
        description="Curated remote jobs, mostly in tech, marketing, customer support and operations.",
        coverage="Remote jobs worldwide. Listings appear with a 24-hour delay.",
        access="Public API (no key required)",
        terms_url="https://github.com/remotive-io/remote-jobs-api",
        attribution="Source: Remotive",
        supported_filters=frozenset({"keywords", "location", "employment_type", "posted_within_days", "employer"}),
        notes=(
            "Remote jobs only.",
            "To respect Remotive's terms, at most 4 new searches per day are sent; repeated searches reuse "
            "results for 6 hours.",
        ),
    )

    def is_enabled(self) -> bool:
        return self.settings.remotive_enabled

    def unsupported_reason(self, query: SearchQuery) -> str | None:
        if query.work_arrangement in (WorkArrangement.ONSITE, WorkArrangement.HYBRID):
            return "Remotive lists remote jobs only."
        return None

    def policy(self) -> RequestPolicy:
        return RequestPolicy(
            min_interval_s=35.0,  # well under Remotive's 2-requests-per-minute block
            daily_limit=self.settings.remotive_daily_limit,
            cache_ttl_s=self.settings.remotive_cache_hours * 3600,
        )

    @staticmethod
    def search_term(query: SearchQuery) -> str:
        """Remotive matches one phrase; with comma-separated alternatives the first is sent."""
        groups = keyword_groups(query.keywords)
        return " ".join(groups[0]) if groups else query.keywords

    def search(self, query: SearchQuery, http: ProviderHttp) -> SearchPage:
        params = {"search": self.search_term(query), "limit": 100}
        response = http.get_json(self.info.id, API_URL, params=params, policy=self.policy())
        jobs = apply_local_filters(self.parse(response.payload), query)
        return SearchPage(jobs, response.from_cache, response.fetched_at)

    def parse(self, payload: Any) -> list[JobPosting]:
        if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
            raise ProviderResponseError("Remotive returned data in an unexpected format.")
        jobs = []
        for item in payload["jobs"]:
            job = self._to_posting(item)
            if job is not None:
                jobs.append(job)
        return jobs

    def _to_posting(self, item: Any) -> JobPosting | None:
        if not isinstance(item, dict):
            return None
        title = clean_text(item.get("title"))
        if not title:
            return None
        tags = item.get("tags") if isinstance(item.get("tags"), list) else []
        return JobPosting(
            provider_id=self.info.id,
            source_name=self.info.name,
            source_url=self.info.website,
            source_job_id=str(item["id"]) if item.get("id") is not None else None,
            title=title,
            company=clean_text(item.get("company_name")),
            location=clean_text(item.get("candidate_required_location")),
            work_arrangement=WorkArrangement.REMOTE,
            employment_type=parse_employment_type(item.get("job_type")),
            salary_text=clean_text(item.get("salary")),
            posted_at=parse_datetime(item.get("publication_date")),
            description=html_to_text(item.get("description")),
            tags=tuple(t for t in (clean_text(x, 60) for x in tags) if t),
            category=clean_text(item.get("category")),
            listing_url=item.get("url"),
            apply_url=None,  # Remotive provides its own listing page, not a direct employer application link
        )
