import httpx
import pytest

from config.settings import Settings
from src.jobs.filtering import matches_location
from src.jobs.models import EmploymentType, JobPosting, SearchQuery, WorkArrangement
from src.pages.find_jobs import filters_not_applied
from src.providers.adapters.adzuna import AdzunaProvider
from src.providers.adapters.himalayas import HimalayasProvider
from src.providers.adapters.jobicy import JobicyProvider
from src.providers.adapters.remoteok import RemoteOKProvider
from src.providers.base import ProviderError, ProviderResponseError
from src.providers.http import ProviderHttp
from src.services.job_search import search_jobs
from tests.fixtures import provider_payloads as pp


def settings(**kw) -> Settings:
    kw.setdefault("offline_mode", False)
    return Settings(_env_file=None, **kw)


def http_for(routes: dict[str, object], seen: list | None = None) -> ProviderHttp:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        for host, payload in routes.items():
            if host in request.url.host:
                if isinstance(payload, int):
                    return httpx.Response(payload)
                return httpx.Response(200, json=payload)
        return httpx.Response(404)

    return ProviderHttp(transport=httpx.MockTransport(handler), sleep=lambda s: None)


# --- Himalayas -------------------------------------------------------------

def test_himalayas_parse():
    jobs = HimalayasProvider(settings()).parse(pp.himalayas_payload())
    assert len(jobs) == 2
    j = jobs[0]
    assert (j.title, j.company, j.location) == ("Quality Engineer", "Example Devices", "Worldwide")
    assert j.employment_type is EmploymentType.FULL_TIME and j.work_arrangement is WorkArrangement.REMOTE
    assert (j.salary_min, j.salary_max, j.salary_currency, j.salary_period) == (90000, 110000, "USD", "annual")
    assert j.listing_url == "https://himalayas.app/companies/example/jobs/quality-engineer" and j.apply_url is None
    assert j.posted_at is not None and "FMEA" in j.description
    assert jobs[1].location == "Canada" and jobs[1].employment_type is EmploymentType.CONTRACT


def test_himalayas_sends_query_and_country():
    seen: list = []
    page = HimalayasProvider(settings()).search(
        SearchQuery(keywords="quality", country="ca", employment_type=EmploymentType.CONTRACT),
        http_for({"himalayas.app": pp.himalayas_payload()}, seen))
    params = seen[0].url.params
    assert params["q"] == "quality" and params["country"] == "CA" and params["employment_type"] == "Contractor"
    # The full-time job is excluded by the Contract filter; the Canada-restricted contract job remains.
    assert {j.title for j in page.jobs} == {"Quality Analyst"}


# --- Jobicy ----------------------------------------------------------------

def test_jobicy_parse_and_excerpt_fallback():
    jobs = JobicyProvider(settings()).parse(pp.jobicy_payload())
    assert jobs[0].location == "USA" and jobs[0].salary_period == "yearly"
    assert jobs[0].listing_url == "https://jobicy.com/jobs/155742-quality-engineer"
    assert jobs[1].description == "Excerpt only"  # full description missing → excerpt used, not invented
    assert jobs[1].employment_type is EmploymentType.CONTRACT


def test_jobicy_reports_api_failure():
    with pytest.raises(ProviderResponseError):
        JobicyProvider(settings()).parse({"success": False, "jobs": []})


# --- Remote OK -------------------------------------------------------------

def test_remoteok_skips_legal_notice_and_keeps_blank_location_blank():
    jobs = RemoteOKProvider(settings()).parse(pp.remoteok_payload())
    assert [j.title for j in jobs] == ["Quality Engineer", "Head of Technology"]
    assert jobs[0].location is None and jobs[0].salary_min is None  # 0 means not provided
    assert jobs[1].salary_min == 140000 and jobs[1].salary_max is None
    assert all(j.apply_url is None for j in jobs)


def test_remoteok_local_keyword_filter():
    page = RemoteOKProvider(settings()).search(SearchQuery(keywords="quality engineer"),
                                               http_for({"remoteok.com": pp.remoteok_payload()}))
    assert [j.title for j in page.jobs] == ["Quality Engineer"]


def test_remoteok_invalid_payload():
    with pytest.raises(ProviderResponseError):
        RemoteOKProvider(settings()).parse({"not": "a list"})


# --- Adzuna ----------------------------------------------------------------

def keyed(**kw) -> Settings:
    return settings(adzuna_app_id="test-id", adzuna_app_key="test-secret-key", **kw)


def test_adzuna_requires_credentials_and_country():
    assert AdzunaProvider(settings()).missing_configuration() == ["CAREERMATCH_ADZUNA_APP_ID",
                                                                   "CAREERMATCH_ADZUNA_APP_KEY"]
    p = AdzunaProvider(keyed())
    assert "Choose a country" in p.unsupported_reason(SearchQuery(keywords="qa"))
    assert "does not cover" in p.unsupported_reason(SearchQuery(keywords="qa", country="pk"))
    assert p.unsupported_reason(SearchQuery(keywords="qa", country="gb")) is None
    assert AdzunaProvider(keyed(adzuna_default_country="gb")).unsupported_reason(SearchQuery(keywords="qa")) is None


def test_adzuna_request_params_and_parse():
    seen: list = []
    q = SearchQuery(keywords="quality engineer", country="gb", location="Manchester", posted_within_days=7,
                    salary_min=30000, employment_type=EmploymentType.FULL_TIME)
    page = AdzunaProvider(keyed()).search(q, http_for({"adzuna.com": pp.adzuna_payload()}, seen))
    req = seen[0]
    assert req.url.path == "/v1/api/jobs/gb/search/1"
    params = req.url.params
    assert params["what"] == "quality engineer" and params["where"] == "Manchester"
    assert params["max_days_old"] == "7" and params["salary_min"] == "30000" and params["full_time"] == "1"
    j = page.jobs[0]
    assert j.title == "Quality Engineer"  # highlight markup removed
    assert j.company == "Example Plc" and j.country == "gb" and j.salary_currency == "GBP"
    assert j.salary_is_estimate and j.salary_period is None  # period not stated by Adzuna → not guessed
    assert j.employment_type is EmploymentType.FULL_TIME
    assert j.listing_url == "https://www.adzuna.co.uk/jobs/land/ad/4321" and j.apply_url is None


def test_adzuna_missing_company_and_salary_not_invented():
    jobs = AdzunaProvider(keyed()).parse(pp.adzuna_payload(), "gb")
    j = jobs[1]
    assert j.company is None and j.salary_currency is None and j.employment_type is EmploymentType.CONTRACT


def test_adzuna_rejected_key_message_has_no_secret():
    page_error = None
    try:
        AdzunaProvider(keyed()).search(SearchQuery(keywords="qa", country="gb"), http_for({"adzuna.com": 401}))
    except ProviderError as exc:
        page_error = exc.message
    assert page_error and "test-secret-key" not in page_error and "test-id" not in page_error


def test_adzuna_secret_not_in_settings_repr():
    assert "test-secret-key" not in repr(keyed())


# --- Cross-provider --------------------------------------------------------

def test_multi_source_search_partial_failure():
    s = keyed()
    http = http_for({"himalayas.app": pp.himalayas_payload(), "jobicy.com": 503, "remoteok.com": pp.remoteok_payload(),
                     "remotive.com": {"jobs": []}, "adzuna.com": pp.adzuna_payload()})
    outcome = search_jobs(SearchQuery(keywords="quality engineer", country="gb"), s, http)
    by_id = {r.provider_id: r for r in outcome.results}
    assert by_id["jobicy"].status == "error" and by_id["jobicy"].retryable
    assert by_id["himalayas"].status == "ok" and by_id["adzuna"].status == "ok"
    assert {j.provider_id for j in outcome.jobs} >= {"himalayas", "adzuna", "remoteok"}


def test_onsite_search_skips_remote_only_boards():
    outcome = search_jobs(SearchQuery(keywords="quality", country="gb", work_arrangement=WorkArrangement.ONSITE),
                          keyed(), http_for({"adzuna.com": pp.adzuna_payload()}))
    statuses = {r.provider_id: r.status for r in outcome.results}
    assert statuses["adzuna"] == "ok"
    assert all(statuses[p] == "skipped" for p in ("himalayas", "jobicy", "remoteok", "remotive"))


def test_filters_not_applied_are_reported_per_source():
    outcome = search_jobs(SearchQuery(keywords="quality engineer", salary_min=50000),
                          settings(), http_for({"himalayas.app": pp.himalayas_payload(), "jobicy.com": pp.jobicy_payload(),
                                                "remoteok.com": pp.remoteok_payload(), "remotive.com": {"jobs": []}}))
    notes = " ".join(filters_not_applied(outcome))
    assert "Himalayas did not filter by minimum salary" in notes


@pytest.mark.parametrize("job_loc,country,keep", [
    ("USA", "us", True), ("United States", "us", True), ("Canada", "us", False), (None, "us", True),
    ("Worldwide", "pk", True), ("UAE, Saudi Arabia", "ae", True), ("Europe", None, True),
])
def test_matches_location_with_country(job_loc, country, keep):
    job = JobPosting(provider_id="x", source_name="X", title="T", location=job_loc)
    assert matches_location(job, None, country) is keep
