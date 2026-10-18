"""Jobicy public remote-jobs API.

Docs: https://jobicy.com/jobs-rss-feed
- No key required for the public API. Listings cover the last 7 days with a short delay.
- Jobicy must be credited with a clickable link, and application buttons must use the
  original job URL from the feed. Excessive requests should be avoided.
"""

from __future__ import annotations

from typing import Any

from src.jobs.filtering import apply_local_filters, keyword_groups
from src.jobs.models import JobPosting, SearchQuery, WorkArrangement
from src.jobs.normalization import clean_text, html_to_text, parse_datetime, positive_number
from src.providers.adapters._common import first_employment_type, str_list
from src.providers.base import JobProvider, ProviderInfo, ProviderResponseError, SearchPage
from src.providers.http import ProviderHttp, RequestPolicy

API_URL = "https://jobicy.com/api/v2/remote-jobs"


class JobicyProvider(JobProvider):
    info = ProviderInfo(
        id="jobicy",
        name="Jobicy",
        website="https://jobicy.com",
        description="Remote jobs across engineering, marketing, operations and more.",
        coverage="Remote jobs posted in the last 7 days.",
        access="Public API (no key required)",
        terms_url="https://jobicy.com/jobs-rss-feed",
        attribution="Source: Jobicy",
        supported_filters=frozenset({"keywords", "location", "employment_type", "posted_within_days", "employer"}),
        notes=("Remote jobs only.", "Only jobs from the last 7 days are available.",
               "Repeated searches reuse results for one hour."),
    )

    def is_enabled(self) -> bool:
        return self.settings.jobicy_enabled

    def unsupported_reason(self, query: SearchQuery) -> str | None:
        if query.work_arrangement in (WorkArrangement.ONSITE, WorkArrangement.HYBRID):
            return "Jobicy lists remote jobs only."
        return None

    def search(self, query: SearchQuery, http: ProviderHttp) -> SearchPage:
        groups = keyword_groups(query.keywords)
        params = {"count": 50, "tag": " ".join(groups[0]) if groups else query.keywords}
        response = http.get_json(self.info.id, API_URL, params=params,
                                 policy=RequestPolicy(min_interval_s=2.0, cache_ttl_s=3600))
        jobs = apply_local_filters(self.parse(response.payload), query)
        return SearchPage(jobs, response.from_cache, response.fetched_at)

    def parse(self, payload: Any) -> list[JobPosting]:
        if not isinstance(payload, dict) or not isinstance(payload.get("jobs", []), list):
            raise ProviderResponseError("Jobicy returned data in an unexpected format.")
        if payload.get("success") is False:
            raise ProviderResponseError("Jobicy reported an error for this search.")
        return [job for item in payload.get("jobs", []) if (job := self._to_posting(item)) is not None]

    def _to_posting(self, item: Any) -> JobPosting | None:
        if not isinstance(item, dict) or not clean_text(item.get("jobTitle")):
            return None
        currency = clean_text(item.get("salaryCurrency"), 8)
        return JobPosting(
            provider_id=self.info.id,
            source_name=self.info.name,
            source_url=self.info.website,
            source_job_id=str(item["id"]) if item.get("id") is not None else None,
            title=clean_text(item.get("jobTitle")),
            company=clean_text(item.get("companyName")),
            location=clean_text(item.get("jobGeo")),
            work_arrangement=WorkArrangement.REMOTE,
            employment_type=first_employment_type(str_list(item.get("jobType"))),
            salary_min=positive_number(item.get("salaryMin")),
            salary_max=positive_number(item.get("salaryMax")),
            salary_currency=currency.upper() if currency else None,
            salary_period=clean_text(item.get("salaryPeriod"), 20),
            posted_at=parse_datetime(item.get("pubDate")),
            description=html_to_text(item.get("jobDescription")) or (clean_text(item.get("jobExcerpt"), 2000) or ""),
            tags=tuple(str_list(item.get("jobIndustry"), 10)),
            category=(str_list(item.get("jobIndustry")) or [None])[0],
            listing_url=item.get("url"),  # terms: application buttons must use this original job URL
            apply_url=None,
        )
