"""Remote OK public API.

Terms (returned in the API's legal notice): link back to the Remote OK URL (followed, without
nofollow) and mention Remote OK as the source. The logo must not be used without permission.
The API returns its current feed, which is searched locally.
"""

from __future__ import annotations

from typing import Any

from src.jobs.filtering import apply_local_filters
from src.jobs.models import JobPosting, SearchQuery, WorkArrangement
from src.jobs.normalization import clean_text, html_to_text, parse_datetime, positive_number
from src.providers.adapters._common import str_list
from src.providers.base import JobProvider, ProviderInfo, ProviderResponseError, SearchPage
from src.providers.http import ProviderHttp, RequestPolicy

API_URL = "https://remoteok.com/api"


class RemoteOKProvider(JobProvider):
    info = ProviderInfo(
        id="remoteok",
        name="Remote OK",
        website="https://remoteok.com",
        description="A large remote job board, strongest in software and digital roles.",
        coverage="Its current feed of recent remote jobs (about 100 listings).",
        access="Public API (no key required)",
        terms_url="https://remoteok.com/api",
        attribution="Source: Remote OK",
        supported_filters=frozenset({"keywords", "location", "posted_within_days", "employer"}),
        notes=("Remote jobs only.", "Only the current feed is searchable; it is refreshed at most hourly."),
    )

    def is_enabled(self) -> bool:
        return self.settings.remoteok_enabled

    def unsupported_reason(self, query: SearchQuery) -> str | None:
        if query.work_arrangement in (WorkArrangement.ONSITE, WorkArrangement.HYBRID):
            return "Remote OK lists remote jobs only."
        return None

    def search(self, query: SearchQuery, http: ProviderHttp) -> SearchPage:
        response = http.get_json(self.info.id, API_URL, policy=RequestPolicy(min_interval_s=2.0, cache_ttl_s=3600))
        jobs = apply_local_filters(self.parse(response.payload), query)
        return SearchPage(jobs, response.from_cache, response.fetched_at)

    def parse(self, payload: Any) -> list[JobPosting]:
        if not isinstance(payload, list):
            raise ProviderResponseError("Remote OK returned data in an unexpected format.")
        # The first element is the legal notice, not a job.
        return [job for item in payload if (job := self._to_posting(item)) is not None]

    def _to_posting(self, item: Any) -> JobPosting | None:
        if not isinstance(item, dict) or "legal" in item or not clean_text(item.get("position")):
            return None
        tags = str_list(item.get("tags"), 15)
        return JobPosting(
            provider_id=self.info.id,
            source_name=self.info.name,
            source_url=self.info.website,
            source_job_id=str(item["id"]) if item.get("id") is not None else None,
            title=clean_text(item.get("position")),
            company=clean_text(item.get("company")),
            location=clean_text(item.get("location")),  # empty means not stated — left blank, not guessed
            work_arrangement=WorkArrangement.REMOTE,
            salary_min=positive_number(item.get("salary_min")),
            salary_max=positive_number(item.get("salary_max")),
            posted_at=parse_datetime(item.get("date")) or parse_datetime(positive_number(item.get("epoch"))),
            description=html_to_text(item.get("description")),
            tags=tuple(tags),
            listing_url=item.get("url"),
            apply_url=None,  # Remote OK's apply_url points to its own listing page, not an employer form
        )
