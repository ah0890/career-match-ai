"""Himalayas public remote-jobs search API.

Docs and terms: https://himalayas.app/api
- No key required (requests without a key share a public allowance; cached responses are free).
- Link back to Himalayas and name it as the source; Apply actions must use the supplied
  ``applicationLink``. Do not resubmit jobs to other boards or aggregators.
"""

from __future__ import annotations

from typing import Any

from src.jobs.filtering import apply_local_filters, keyword_groups
from src.jobs.models import EmploymentType, JobPosting, SearchQuery, WorkArrangement
from src.jobs.normalization import clean_text, html_to_text, parse_datetime, parse_expiry, positive_number
from src.providers.adapters._common import first_employment_type, str_list
from src.providers.base import JobProvider, ProviderInfo, ProviderResponseError, SearchPage
from src.providers.http import ProviderHttp, RequestPolicy

API_URL = "https://himalayas.app/jobs/api/search"
_EMPLOYMENT_PARAM = {
    EmploymentType.FULL_TIME: "Full Time", EmploymentType.PART_TIME: "Part Time",
    EmploymentType.CONTRACT: "Contractor", EmploymentType.TEMPORARY: "Temporary",
    EmploymentType.INTERNSHIP: "Intern",
}


class HimalayasProvider(JobProvider):
    info = ProviderInfo(
        id="himalayas",
        name="Himalayas",
        website="https://himalayas.app",
        description="Remote jobs from companies hiring remotely, with salary and location restrictions.",
        coverage="Remote jobs worldwide.",
        access="Public API (no key required)",
        terms_url="https://himalayas.app/api",
        attribution="Source: Himalayas",
        supported_filters=frozenset({"keywords", "country", "location", "employment_type", "posted_within_days",
                                     "employer"}),
        notes=("Remote jobs only.", "Repeated searches reuse results for one hour."),
    )

    def is_enabled(self) -> bool:
        return self.settings.himalayas_enabled

    def unsupported_reason(self, query: SearchQuery) -> str | None:
        if query.work_arrangement in (WorkArrangement.ONSITE, WorkArrangement.HYBRID):
            return "Himalayas lists remote jobs only."
        return None

    def search(self, query: SearchQuery, http: ProviderHttp) -> SearchPage:
        groups = keyword_groups(query.keywords)
        params: dict[str, Any] = {"q": " ".join(groups[0]) if groups else query.keywords}
        if query.country:
            params["country"] = query.country.upper()
        if query.employment_type in _EMPLOYMENT_PARAM:
            params["employment_type"] = _EMPLOYMENT_PARAM[query.employment_type]
        response = http.get_json(self.info.id, API_URL, params=params,
                                 policy=RequestPolicy(min_interval_s=1.0, cache_ttl_s=3600))
        jobs = apply_local_filters(self.parse(response.payload), query)
        return SearchPage(jobs, response.from_cache, response.fetched_at)

    def parse(self, payload: Any) -> list[JobPosting]:
        if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
            raise ProviderResponseError("Himalayas returned data in an unexpected format.")
        return [job for item in payload["jobs"] if (job := self._to_posting(item)) is not None]

    def _to_posting(self, item: Any) -> JobPosting | None:
        if not isinstance(item, dict) or not clean_text(item.get("title")):
            return None
        restrictions = str_list(item.get("locationRestrictions"))
        currency = clean_text(item.get("currency"), 8)
        return JobPosting(
            provider_id=self.info.id,
            source_name=self.info.name,
            source_url=self.info.website,
            source_job_id=clean_text(item.get("guid"), 400),
            title=clean_text(item.get("title")),
            company=clean_text(item.get("companyName")),
            # Himalayas uses an empty restriction list for jobs open to candidates anywhere.
            location=", ".join(restrictions) if restrictions else "Worldwide",
            work_arrangement=WorkArrangement.REMOTE,
            employment_type=first_employment_type(str_list(item.get("employmentType"))),
            salary_min=positive_number(item.get("minSalary")),
            salary_max=positive_number(item.get("maxSalary")),
            salary_currency=currency.upper() if currency else None,
            salary_period=clean_text(item.get("salaryPeriod"), 20),
            posted_at=parse_datetime(positive_number(item.get("pubDate"))),
            expires_at=parse_expiry(positive_number(item.get("expiryDate"))),
            description=html_to_text(item.get("description")),
            tags=tuple(str_list(item.get("categories"), 10)),
            category=(str_list(item.get("parentCategories")) or [None])[0],
            listing_url=item.get("applicationLink"),  # terms: Apply actions must use this link
            apply_url=None,  # it is a Himalayas page, not a verified employer application form
        )
