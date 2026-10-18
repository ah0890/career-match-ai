"""Adzuna job search API (requires a free app_id/app_key).

Docs: https://developer.adzuna.com/docs/search · Terms: https://developer.adzuna.com/docs/terms_of_service
- Each displayed advert must be labelled "Adzuna" (at least 116×23 px) and linked to Adzuna.
- Default limits: 25 requests/minute, 250/day, 1,000/week, 2,500/month.
- Personal use is permitted; ongoing commercial use requires Adzuna's written consent.
- Descriptions are short snippets; the full advert is on the linked listing page.
"""

from __future__ import annotations

from typing import Any

from src.jobs.filtering import apply_local_filters, keyword_groups
from src.jobs.models import EmploymentType, JobPosting, SearchQuery
from src.jobs.normalization import clean_text, html_to_text, parse_datetime, positive_number
from src.providers.base import JobProvider, ProviderInfo, ProviderResponseError, SearchPage
from src.providers.http import ProviderHttp, RequestPolicy

API_URL = "https://api.adzuna.com/v1/api/jobs/{country}/search/1"

# Countries reported as covered by the Adzuna API (secondary sources agree on these 19; unsupported
# countries are rejected by the API and reported as an error rather than guessed).
SUPPORTED_COUNTRIES: dict[str, str] = {
    "gb": "United Kingdom", "us": "United States", "at": "Austria", "au": "Australia", "be": "Belgium",
    "br": "Brazil", "ca": "Canada", "ch": "Switzerland", "de": "Germany", "es": "Spain", "fr": "France",
    "in": "India", "it": "Italy", "mx": "Mexico", "nl": "Netherlands", "nz": "New Zealand", "pl": "Poland",
    "sg": "Singapore", "za": "South Africa",
}
_CURRENCY = {"gb": "GBP", "us": "USD", "at": "EUR", "au": "AUD", "be": "EUR", "br": "BRL", "ca": "CAD",
             "ch": "CHF", "de": "EUR", "es": "EUR", "fr": "EUR", "in": "INR", "it": "EUR", "mx": "MXN",
             "nl": "EUR", "nz": "NZD", "pl": "PLN", "sg": "SGD", "za": "ZAR"}
_EMPLOYMENT_PARAM = {EmploymentType.FULL_TIME: "full_time", EmploymentType.PART_TIME: "part_time",
                     EmploymentType.CONTRACT: "contract"}


class AdzunaProvider(JobProvider):
    info = ProviderInfo(
        id="adzuna",
        name="Adzuna",
        website="https://www.adzuna.com",
        description="A job search engine aggregating vacancies from many employers and job boards.",
        coverage="On-site, hybrid and remote jobs in " + ", ".join(sorted(SUPPORTED_COUNTRIES.values())) + ".",
        access="Official API (free key required)",
        terms_url="https://developer.adzuna.com/docs/terms_of_service",
        attribution="Jobs by Adzuna",
        supported_filters=frozenset({"keywords", "location", "country", "employment_type", "posted_within_days",
                                     "salary_min", "employer"}),
        credential_env_vars=("CAREERMATCH_ADZUNA_APP_ID", "CAREERMATCH_ADZUNA_APP_KEY"),
        notes=("Requires a country from the supported list.",
               "Descriptions are short snippets; open the listing for full details.",
               "Free keys are limited to 250 requests per day."),
    )

    def is_enabled(self) -> bool:
        return self.settings.adzuna_enabled

    def missing_configuration(self) -> list[str]:
        missing = []
        if not self.settings.adzuna_app_id:
            missing.append("CAREERMATCH_ADZUNA_APP_ID")
        if not self.settings.adzuna_app_key:
            missing.append("CAREERMATCH_ADZUNA_APP_KEY")
        return missing

    def _country(self, query: SearchQuery) -> str | None:
        return query.country or self.settings.adzuna_default_country

    def unsupported_reason(self, query: SearchQuery) -> str | None:
        country = self._country(query)
        if not country:
            return "Choose a country to search Adzuna."
        if country not in SUPPORTED_COUNTRIES:
            return "Adzuna does not cover the selected country."
        return None

    def search(self, query: SearchQuery, http: ProviderHttp) -> SearchPage:
        country = self._country(query)
        assert country is not None  # guarded by unsupported_reason
        groups = keyword_groups(query.keywords)
        params: dict[str, Any] = {
            "app_id": self.settings.adzuna_app_id,
            "app_key": self.settings.adzuna_app_key.get_secret_value() if self.settings.adzuna_app_key else "",
            "what": " ".join(groups[0]) if groups else query.keywords,
            "results_per_page": 50,
            "content-type": "application/json",
        }
        if query.location:
            params["where"] = query.location
        if query.posted_within_days:
            params["max_days_old"] = query.posted_within_days
        if query.salary_min:
            params["salary_min"] = query.salary_min
        if query.employment_type in _EMPLOYMENT_PARAM:
            params[_EMPLOYMENT_PARAM[query.employment_type]] = 1
        if query.employer:
            params["company"] = query.employer
        response = http.get_json(
            self.info.id, API_URL.format(country=country), params=params,
            policy=RequestPolicy(min_interval_s=2.5, daily_limit=self.settings.adzuna_daily_limit, cache_ttl_s=3600),
        )
        # Location and country are already applied by Adzuna server-side; local text matching of place names
        # would wrongly drop jobs such as "Manchester" for country "gb".
        jobs = apply_local_filters(self.parse(response.payload, country),
                                   query.model_copy(update={"location": None, "country": None}))
        return SearchPage(jobs, response.from_cache, response.fetched_at)

    def parse(self, payload: Any, country: str) -> list[JobPosting]:
        if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
            raise ProviderResponseError("Adzuna returned data in an unexpected format.")
        return [job for item in payload["results"] if (job := self._to_posting(item, country)) is not None]

    def _to_posting(self, item: Any, country: str) -> JobPosting | None:
        if not isinstance(item, dict) or not clean_text(item.get("title")):
            return None
        company = item.get("company") if isinstance(item.get("company"), dict) else {}
        location = item.get("location") if isinstance(item.get("location"), dict) else {}
        category = item.get("category") if isinstance(item.get("category"), dict) else {}
        contract_time = clean_text(item.get("contract_time"), 30)
        contract_type = clean_text(item.get("contract_type"), 30)
        if contract_type == "contract":
            employment = EmploymentType.CONTRACT
        elif contract_time == "full_time":
            employment = EmploymentType.FULL_TIME
        elif contract_time == "part_time":
            employment = EmploymentType.PART_TIME
        else:
            employment = EmploymentType.UNKNOWN
        has_salary = positive_number(item.get("salary_min")) or positive_number(item.get("salary_max"))
        return JobPosting(
            provider_id=self.info.id,
            source_name=self.info.name,
            source_url=self.info.website,
            source_job_id=str(item["id"]) if item.get("id") is not None else None,
            title=html_to_text(clean_text(item.get("title"))),  # Adzuna titles may contain <strong> highlights
            company=clean_text(company.get("display_name")),
            location=clean_text(location.get("display_name")),
            country=country,
            employment_type=employment,
            salary_min=positive_number(item.get("salary_min")),
            salary_max=positive_number(item.get("salary_max")),
            salary_currency=_CURRENCY.get(country) if has_salary else None,
            salary_is_estimate=str(item.get("salary_is_predicted")) == "1",
            posted_at=parse_datetime(item.get("created")),
            description=html_to_text(item.get("description")),
            category=clean_text(category.get("label")),
            listing_url=item.get("redirect_url"),
            apply_url=None,  # Adzuna links to its listing/redirect page, not a verified application form
        )
