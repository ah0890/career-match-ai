from datetime import datetime, timedelta, timezone

import pytest

from src.jobs.deduplication import deduplicate, is_duplicate
from src.jobs.freshness import Freshness, assess
from src.jobs.models import JobPosting
from src.jobs.normalization import canonical_url, normalize_company, normalize_title, parse_expiry

NOW = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)
LONG = ("Own the quality management system, lead FMEA and SPC programmes, coordinate supplier audits, "
        "and drive corrective actions across production lines in close cooperation with engineering. ") * 3


def job(pid="himalayas", **kw) -> JobPosting:
    base = dict(provider_id=pid, source_name=pid.title(), title="Quality Engineer", company="Example Devices Ltd",
                location="Worldwide", listing_url=f"https://{pid}.example.com/jobs/1", description=LONG)
    base.update(kw)
    return JobPosting(**base)


# --- Normalisation ---------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("Example Analytics Ltd.", "example analytics"), ("The Example Analytics, LLC", "example analytics"),
    ("Coca-Cola Company", "coca cola"), ("Costco", "costco"), (None, ""),
])
def test_normalize_company(raw, expected):
    assert normalize_company(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("Sr. Data Analyst (Remote)", "senior data analyst"), ("Remote - Senior Data Analyst", "senior data analyst"),
    ("Data Analyst (m/f/d)", "data analyst"), ("Jr Developer", "junior developer"),
    ("Remote Sensing Analyst", "remote sensing analyst"), ("C++ Developer", "c++ developer"),
])
def test_normalize_title(raw, expected):
    assert normalize_title(raw) == expected


def test_canonical_url_strips_tracking():
    assert canonical_url("https://WWW.Example.com/jobs/1/?utm_source=x&id=5#top") == "https://example.com/jobs/1?id=5"
    assert canonical_url(None) is None


def test_listing_url_never_doubles_as_apply_url():
    j = job(listing_url="https://example.com/jobs/1", apply_url="https://example.com/jobs/1/")
    assert j.apply_url is None


# --- Duplicate detection ---------------------------------------------------

def test_same_job_on_two_sources_is_merged_and_provenance_kept():
    a = job("himalayas", posted_at=None)
    b = job("jobicy", title="Quality Engineer (Remote)", company="Example Devices", posted_at=NOW - timedelta(days=2))
    result = deduplicate([a, b])
    assert result.duplicates_merged == 1 and len(result.jobs) == 1
    merged = result.jobs[0]
    others = {l.provider_id for l in merged.also_listed_on} | {merged.provider_id}
    assert others == {"himalayas", "jobicy"}
    assert merged.posted_at == NOW - timedelta(days=2)  # date reported by the other source is reused


def test_same_url_is_duplicate_even_with_different_titles():
    assert is_duplicate(job("a", listing_url="https://x.com/j/1?utm_source=a"),
                        job("b", title="QE", listing_url="https://www.x.com/j/1/"))


@pytest.mark.parametrize("other", [
    {"title": "Senior Quality Engineer"},                      # different seniority
    {"title": "Quality Manager"},                              # different role
    {"company": "Other Devices"},                              # different employer
    {"location": "Germany", "description": LONG},              # incompatible location
    {"description": "Completely different role about sales targets and CRM pipelines. " * 6},
])
def test_different_positions_are_not_merged(other):
    a = job("himalayas", location="United States")
    b = job("jobicy", **other)
    assert not is_duplicate(a, b)
    assert deduplicate([a, b]).duplicates_merged == 0


def test_missing_company_is_never_merged_on_title_alone():
    assert not is_duplicate(job("a", company=None), job("b", company=None))


def test_richest_posting_becomes_primary():
    thin = job("remoteok", description="Short.")
    rich = job("himalayas", salary_min=90000, listing_url="https://himalayas.app/j/1")
    merged = deduplicate([thin, rich]).jobs[0]
    assert merged.provider_id == "himalayas"
    assert merged.also_listed_on[0].provider_id == "remoteok"


def test_three_way_merge_keeps_one_link_per_source():
    jobs = [job("a"), job("b"), job("c", listing_url="https://a.example.com/jobs/1")]
    result = deduplicate(jobs)
    assert len(result.jobs) == 1 and result.duplicates_merged == 2
    assert len(result.jobs[0].also_listed_on) == 2


# --- Freshness -------------------------------------------------------------

@pytest.mark.parametrize("days,status", [(0, Freshness.RECENT), (7, Freshness.RECENT), (8, Freshness.OLDER),
                                         (30, Freshness.OLDER), (31, Freshness.POSSIBLY_STALE)])
def test_freshness_by_age(days, status):
    info = assess(job(posted_at=NOW - timedelta(days=days)), NOW)
    assert info.status is status
    assert "not confirmed" in info.explanation


def test_missing_date_is_unverified_not_recent():
    info = assess(job(posted_at=None), NOW)
    assert info.status is Freshness.UNVERIFIED and info.label == "Date not provided"


def test_expired_listing():
    info = assess(job(posted_at=NOW - timedelta(days=3), expires_at=NOW - timedelta(days=1)), NOW)
    assert info.status is Freshness.EXPIRED


def test_parse_expiry_allows_future_dates():
    assert parse_expiry(1794790336) is not None
    assert parse_expiry("garbage") is None
