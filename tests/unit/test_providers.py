from datetime import date

import httpx
import pytest

from config.settings import Settings
from src.jobs.models import EmploymentType, JobPosting, SearchQuery, WorkArrangement, safe_url
from src.jobs.normalization import html_to_text, parse_datetime
from src.providers.adapters.remotive import RemotiveProvider
from src.providers.base import (
    JobProvider, ProviderError, ProviderInfo, ProviderRateLimited, ProviderResponseError, ProviderTimeout,
    ProviderUnavailable, SearchPage,
)
from src.providers.http import ProviderHttp, RequestPolicy
from src.providers.registry import UNSUPPORTED_SOURCES, provider_status, statuses
from src.services.job_search import search_jobs
from tests.fixtures.provider_payloads import remotive_payload


def settings(**kw) -> Settings:
    kw.setdefault("offline_mode", False)  # explicit: these tests use mocked transports only
    return Settings(_env_file=None, **kw)


class Clock:
    def __init__(self):
        self.t = 1000.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.slept.append(s)
        self.t += s


def make_http(handler, *, clock: Clock | None = None, **kw) -> ProviderHttp:
    clock = clock or Clock()
    return ProviderHttp(transport=httpx.MockTransport(handler), clock=clock, sleep=clock.sleep, **kw)


def ok_handler(payload):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=payload)

    handler.calls = calls  # type: ignore[attr-defined]
    return handler


# --- Models ----------------------------------------------------------------

@pytest.mark.parametrize("url,ok", [
    ("https://example.com/jobs/1", True), ("http://example.com", True), ("javascript:alert(1)", False),
    ("ftp://example.com/file", False), ("https://user:pass@example.com", False), ("example.com/job", False),
    ("https://localhost/job", False), ("https://exa mple.com", False), (None, False), ("", False),
])
def test_safe_url(url, ok):
    assert (safe_url(url) is not None) is ok


def test_job_posting_drops_unsafe_urls_and_requires_title():
    job = JobPosting(provider_id="x", source_name="X", title="  Data   Analyst ", listing_url="javascript:x()")
    assert job.title == "Data Analyst" and job.listing_url is None
    with pytest.raises(ValueError):
        JobPosting(provider_id="x", source_name="X", title="   ")


def test_search_query_validation():
    with pytest.raises(ValueError):
        SearchQuery(keywords="a")
    with pytest.raises(ValueError):
        SearchQuery(keywords="Analyst", country="PAK")
    assert SearchQuery(keywords="  Analyst ", location="").location is None


def test_html_to_text_strips_scripts_and_keeps_structure():
    text = html_to_text("<p>Hello <b>world</b></p><ul><li>One</li><li>Two</li></ul><script>bad()</script>")
    assert "bad()" not in text and "<" not in text
    assert "- One" in text and "- Two" in text


@pytest.mark.parametrize("value,ok", [
    ("2026-01-05T10:00:00", True), ("2026-01-05T10:00:00Z", True), (1767600000, True),
    ("not a date", False), (None, False), (0, False), ("2999-01-01T00:00:00", False),
])
def test_parse_datetime(value, ok):
    assert (parse_datetime(value) is not None) is ok


# --- HTTP layer ------------------------------------------------------------

def test_http_caches_responses_within_ttl():
    handler = ok_handler({"a": 1})
    clock = Clock()
    http = make_http(handler, clock=clock)
    policy = RequestPolicy(min_interval_s=0, cache_ttl_s=60)
    first = http.get_json("p", "https://api.example.com/x", policy=policy)
    second = http.get_json("p", "https://api.example.com/x", policy=policy)
    assert not first.from_cache and second.from_cache
    assert len(handler.calls) == 1
    clock.t += 61
    assert not http.get_json("p", "https://api.example.com/x", policy=policy).from_cache
    assert len(handler.calls) == 2


def test_http_daily_budget_enforced():
    http = make_http(ok_handler({}), today=lambda: date(2026, 1, 1))
    policy = RequestPolicy(min_interval_s=0, daily_limit=2, cache_ttl_s=0)
    http.get_json("p", "https://api.example.com/1", policy=policy)
    http.get_json("p", "https://api.example.com/2", policy=policy)
    with pytest.raises(ProviderRateLimited, match="daily request limit"):
        http.get_json("p", "https://api.example.com/3", policy=policy)
    assert http.requests_today("p") == 2


def test_http_spacing_between_requests():
    clock = Clock()
    http = make_http(ok_handler({}), clock=clock)
    policy = RequestPolicy(min_interval_s=30, cache_ttl_s=0)
    http.get_json("p", "https://api.example.com/1", policy=policy)
    http.get_json("p", "https://api.example.com/2", policy=policy)
    assert clock.slept and clock.slept[-1] == pytest.approx(30)


def test_http_retries_then_succeeds():
    attempts = {"n": 0}

    def handler(request):
        attempts["n"] += 1
        return httpx.Response(503) if attempts["n"] < 3 else httpx.Response(200, json={"ok": True})

    http = make_http(handler)
    assert http.get_json("p", "https://api.example.com", policy=RequestPolicy(min_interval_s=0)).payload == {"ok": True}
    assert attempts["n"] == 3


@pytest.mark.parametrize("handler,error", [
    (lambda r: (_ for _ in ()).throw(httpx.ReadTimeout("t", request=r)), ProviderTimeout),
    (lambda r: (_ for _ in ()).throw(httpx.ConnectError("c", request=r)), ProviderUnavailable),
    (lambda r: httpx.Response(429), ProviderRateLimited),
    (lambda r: httpx.Response(500), ProviderUnavailable),
    (lambda r: httpx.Response(404), ProviderResponseError),
    (lambda r: httpx.Response(200, text="<html>not json</html>"), ProviderResponseError),
])
def test_http_errors_are_mapped(handler, error):
    with pytest.raises(error):
        make_http(handler).get_json("p", "https://api.example.com", policy=RequestPolicy(min_interval_s=0))


def test_http_auth_errors_do_not_leak_credentials():
    http = make_http(lambda r: httpx.Response(401))
    with pytest.raises(ProviderError) as info:
        http.get_json("p", "https://api.example.com", params={"app_key": "SECRET123"},
                      policy=RequestPolicy(min_interval_s=0))
    assert "SECRET123" not in info.value.message and "credentials" in info.value.message


def test_offline_mode_blocks_requests_but_serves_cache():
    http = make_http(ok_handler({"a": 1}), offline=True)
    with pytest.raises(ProviderUnavailable, match="Offline"):
        http.get_json("p", "https://api.example.com", policy=RequestPolicy(min_interval_s=0))


# --- Remotive adapter ------------------------------------------------------

def test_remotive_parses_and_normalises():
    jobs = RemotiveProvider(settings()).parse(remotive_payload())
    assert len(jobs) == 4  # the item without a title is skipped
    first = jobs[0]
    assert first.title == "Senior Data Analyst" and first.company == "Example Analytics Ltd"
    assert first.work_arrangement is WorkArrangement.REMOTE
    assert first.employment_type is EmploymentType.FULL_TIME
    assert first.listing_url.startswith("https://remotive.com/")
    assert first.apply_url is None  # never labelled as a direct application link
    assert first.salary_text == "$80k - $95k" and first.salary_min is None  # free text is not converted
    assert "alert" not in first.description and "- Build dashboards" in first.description
    unsafe = next(j for j in jobs if j.company == "Unsafe Link Co")
    assert unsafe.listing_url is None and unsafe.posted_at is None


@pytest.mark.parametrize("payload", [[], {"jobs": "nope"}, {"no_jobs": []}, None])
def test_remotive_invalid_payload(payload):
    with pytest.raises(ProviderResponseError):
        RemotiveProvider(settings()).parse(payload)


def test_remotive_sends_server_side_search_and_caches_identical_queries():
    handler = ok_handler(remotive_payload())
    http = make_http(handler)
    provider = RemotiveProvider(settings())
    page = provider.search(SearchQuery(keywords="data analyst"), http)
    assert handler.calls[0].url.params["search"] == "data analyst"
    assert handler.calls[0].url.params["limit"] == "100"
    # Results are still checked locally, so a broad server match cannot add unrelated jobs.
    assert {j.source_job_id for j in page.jobs} == {"1001", "1003", "1005"}
    again = provider.search(SearchQuery(keywords="data analyst"), http)
    assert again.from_cache and len(handler.calls) == 1
    provider.search(SearchQuery(keywords="backend", location="Germany, Europe"), http)
    assert len(handler.calls) == 2


def test_remotive_daily_budget_stops_new_searches():
    http = make_http(ok_handler(remotive_payload()))
    provider = RemotiveProvider(settings(remotive_daily_limit=2))
    provider.search(SearchQuery(keywords="one"), http)
    provider.search(SearchQuery(keywords="two"), http)
    with pytest.raises(ProviderRateLimited):
        provider.search(SearchQuery(keywords="three"), http)
    assert provider.search(SearchQuery(keywords="one"), http).from_cache  # cached searches still work


def test_remotive_search_term_uses_first_alternative():
    assert RemotiveProvider.search_term(SearchQuery(keywords="Data Analyst, Python")) == "data analyst"


def test_remotive_filters_by_date_and_type():
    http = make_http(ok_handler(remotive_payload()))
    provider = RemotiveProvider(settings())
    recent = provider.search(SearchQuery(keywords="data analyst", posted_within_days=7), http).jobs
    # 1005 has no valid posting date, so it is kept rather than discarded on missing data.
    assert [j.source_job_id for j in recent] == ["1001", "1005"]
    contract = provider.search(SearchQuery(keywords="data analyst", employment_type=EmploymentType.CONTRACT), http).jobs
    assert [j.source_job_id for j in contract] == ["1003", "1005"]  # unknown type kept, full-time excluded


def test_remotive_skips_onsite_queries():
    provider = RemotiveProvider(settings())
    assert provider.unsupported_reason(SearchQuery(keywords="nurse", work_arrangement=WorkArrangement.ONSITE))
    assert provider.unsupported_reason(SearchQuery(keywords="nurse")) is None


def test_remotive_settings_cannot_exceed_terms():
    with pytest.raises(ValueError):
        settings(remotive_daily_limit=10)
    with pytest.raises(ValueError):
        settings(remotive_cache_hours=1)


# --- Registry & service ----------------------------------------------------

def test_status_reflects_configuration():
    by_id = {s.provider.info.id: s for s in statuses(settings())}
    assert {"remotive", "himalayas", "jobicy", "remoteok"} <= {k for k, v in by_id.items() if v.usable}
    assert "adzuna" not in by_id  # removed: only free sources are used
    assert provider_status(RemotiveProvider(settings(remotive_enabled=False))).availability == "disabled"
    assert provider_status(RemotiveProvider(settings(offline_mode=True))).availability == "offline"


def test_unsupported_sources_are_documented():
    names = {s.name for s in UNSUPPORTED_SOURCES}
    assert {"LinkedIn Jobs", "Indeed", "Glassdoor"} <= names
    assert all(s.reason for s in UNSUPPORTED_SOURCES)


class _StubProvider(JobProvider):
    def __init__(self, s, pid, behaviour, needs_key=False):
        super().__init__(s)
        self.info = ProviderInfo(pid, pid.title(), "https://example.com", "", "", "", "https://example.com", "",
                                 frozenset({"keywords"}))
        self.behaviour, self.needs_key = behaviour, needs_key

    def missing_configuration(self):
        return ["CAREERMATCH_X_KEY"] if self.needs_key else []

    def search(self, query, http):
        if isinstance(self.behaviour, Exception):
            raise self.behaviour
        return SearchPage([JobPosting(provider_id=self.info.id, source_name=self.info.name, title="Job")])


def test_search_service_handles_partial_failures_independently():
    s = settings()
    providers = [
        _StubProvider(s, "good", None),
        _StubProvider(s, "slow", ProviderTimeout("The source did not respond in time.")),
        _StubProvider(s, "buggy", RuntimeError("boom with secret details")),
        _StubProvider(s, "nokey", None, needs_key=True),
    ]
    outcome = search_jobs(SearchQuery(keywords="engineer"), s, make_http(ok_handler({})), providers)
    by_id = {r.provider_id: r for r in outcome.results}
    assert by_id["good"].status == "ok" and len(outcome.jobs) == 1
    assert by_id["slow"].status == "error" and by_id["slow"].retryable
    assert by_id["buggy"].status == "error" and "secret" not in by_id["buggy"].message
    assert by_id["nokey"].status == "skipped" and "CAREERMATCH_X_KEY" in by_id["nokey"].message
    assert len(outcome.failed) == 2 and len(outcome.succeeded) == 1
