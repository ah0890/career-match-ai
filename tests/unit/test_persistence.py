"""Persistent HTTP cache, daily budgets across restarts, and search history."""

from datetime import date, datetime, timedelta, timezone

import httpx
import pytest

from config.settings import get_settings
from src.db.http_store import SqlHttpStore, cache_stats, clear_cache
from src.jobs.models import EmploymentType, SearchQuery, WorkArrangement
from src.pages.find_jobs import build_query, form_state
from src.providers.base import ProviderRateLimited, ProviderResult
from src.providers.http import ProviderHttp, RequestPolicy
from src.services.history import HISTORY_LIMIT, clear_history, describe, record_search, recent_searches
from src.services.job_search import SearchOutcome
from tests.fixtures.match_factory import job

POLICY = RequestPolicy(min_interval_s=0, daily_limit=2, cache_ttl_s=3600)


@pytest.fixture
def url():
    return get_settings().database_url


def _client(url, calls, offline=False):
    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, json={"n": len(calls)})
    return ProviderHttp(transport=httpx.MockTransport(handler), sleep=lambda s: None, offline=offline,
                        store=SqlHttpStore(url), today=lambda: date(2026, 10, 19))


def test_cache_survives_restart_and_works_offline(url):
    calls: list = []
    first = _client(url, calls).get_json("remotive", "https://remotive.com/api/x", policy=POLICY)
    assert not first.from_cache
    restarted = _client(url, calls, offline=True)  # new process, no network
    again = restarted.get_json("remotive", "https://remotive.com/api/x", policy=POLICY)
    assert again.from_cache and again.payload == {"n": 1} and len(calls) == 1


def test_daily_limit_survives_restart(url):
    calls: list = []
    _client(url, calls).get_json("remotive", "https://remotive.com/api/a", policy=POLICY)
    _client(url, calls).get_json("remotive", "https://remotive.com/api/b", policy=POLICY)
    fresh = _client(url, calls)
    assert fresh.requests_today("remotive") == 2
    with pytest.raises(ProviderRateLimited):
        fresh.get_json("remotive", "https://remotive.com/api/c", policy=POLICY)


def test_expired_entries_are_not_served(url):
    now = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)
    store = SqlHttpStore(url, now=lambda: now)
    store.put("k", "remotive", {"a": 1}, now - timedelta(hours=7))
    assert store.get("k", 6 * 3600) is None
    assert store.get("k", 8 * 3600)[0] == {"a": 1}


def test_clearing_cache_keeps_request_counts(url):
    calls: list = []
    _client(url, calls).get_json("remotive", "https://remotive.com/api/x", policy=POLICY)
    assert cache_stats(url)[0] == 1
    assert clear_cache(url) == 1 and cache_stats(url) == (0, None)
    assert SqlHttpStore(url).count("remotive", date(2026, 10, 19)) == 1


def test_broken_store_never_breaks_requests():
    store = SqlHttpStore("sqlite:///Z:/definitely/missing/dir/x.db")
    assert store.get("k", 10) is None and store.count("p", date.today()) == 0
    store.put("k", "p", {}, datetime.now(timezone.utc))
    store.increment("p", date.today())


def _outcome(q, n_jobs=1):
    jobs = tuple(job(source_job_id=str(i)) for i in range(n_jobs))
    return SearchOutcome(q, (ProviderResult("himalayas", "Himalayas", "ok", jobs),), datetime.now(timezone.utc),
                         unique_jobs=jobs)


def test_history_records_and_trims(url):
    q = SearchQuery(keywords="Quality Engineer", country="de", work_arrangement=WorkArrangement.REMOTE)
    record_search(url, _outcome(q, 3))
    [past] = recent_searches(url)
    assert past.query == q and past.total_jobs == 3 and past.sources_ok == 1
    assert past.summary == "Quality Engineer · Germany · Remote"
    for i in range(HISTORY_LIMIT + 5):
        record_search(url, _outcome(SearchQuery(keywords=f"Role {i}")))
    assert len(recent_searches(url, limit=500)) == HISTORY_LIMIT
    assert clear_history(url) == HISTORY_LIMIT and recent_searches(url) == []


def test_form_state_round_trips_a_query():
    q = SearchQuery(keywords="Data Analyst", location="Berlin", country="de", work_arrangement=WorkArrangement.HYBRID,
                    employment_type=EmploymentType.CONTRACT, experience_level="Senior", posted_within_days=7,
                    salary_min=50000, required_skills=("SQL", "Python"), industry="Retail")
    assert build_query(form_state(q)) == q


def test_describe_lists_only_set_filters():
    assert describe(SearchQuery(keywords="Analyst")) == "Analyst"
    assert describe(SearchQuery(keywords="Analyst", posted_within_days=3,
                                employment_type=EmploymentType.FULL_TIME)) == "Analyst · full-time · last 3 day(s)"
