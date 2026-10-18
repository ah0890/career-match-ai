from datetime import datetime, timedelta, timezone

from src.jobs.models import EmploymentType, JobPosting, WorkArrangement
from src.providers.base import ProviderResult
from src.ui.job_cards import job_card_html, posted_label, provider_result_badge

NOW = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)


def _job(**kw) -> JobPosting:
    base = dict(provider_id="remotive", source_name="Remotive", source_url="https://remotive.com",
                title="Data Analyst", company="Example Ltd",
                location="Worldwide", listing_url="https://remotive.com/job/1", description="Analyse data.")
    base.update(kw)
    return JobPosting(**base)


def test_card_shows_attribution_and_original_listing_link():
    html = job_card_html(_job(work_arrangement=WorkArrangement.REMOTE, employment_type=EmploymentType.FULL_TIME))
    assert 'Source: <a class="cm-source-link cm-source-remotive" href="https://remotive.com"' in html
    assert 'href="https://remotive.com/job/1"' in html and "View original listing on Remotive" in html
    assert 'rel="noopener"' in html and 'target="_blank"' in html
    assert "nofollow" not in html and "noreferrer" not in html  # sources require followed link-backs
    assert "Apply on employer site" not in html  # never invented
    assert "Remote" in html and "Full-time" in html


def test_card_shows_apply_link_only_when_provided():
    html = job_card_html(_job(apply_url="https://careers.example.com/apply/1"))
    assert "Apply on employer site" in html and "View original listing" in html


def test_card_escapes_provider_content():
    html = job_card_html(_job(title="<img src=x onerror=alert(1)>", company="<b>Evil</b>",
                              description="<script>x</script>"))
    assert "<img" not in html and "<script>" not in html and "<b>Evil" not in html


def test_card_without_links_says_so():
    html = job_card_html(_job(listing_url=None))
    assert "No valid listing link" in html


def test_card_missing_company_and_date_are_labelled_not_guessed():
    html = job_card_html(_job(company=None, posted_at=None))
    assert "Company not provided" in html and "Posting date not provided" in html


def test_card_truncates_long_descriptions():
    html = job_card_html(_job(description="word " * 200))
    assert "…" in html


def test_salary_estimate_is_labelled():
    html = job_card_html(_job(salary_min=50000, salary_max=60000, salary_currency="GBP", salary_is_estimate=True))
    assert "GBP 50,000 – 60,000 (estimated by source)" in html


def test_posted_label():
    assert posted_label(None) == "Posting date not provided"
    assert posted_label(NOW, NOW) == "Posted today"
    assert posted_label(NOW - timedelta(days=1), NOW) == "Posted yesterday"
    assert posted_label(NOW - timedelta(days=5), NOW) == "Posted 5 days ago"
    assert posted_label(NOW - timedelta(days=60), NOW).startswith("Posted 19 Aug 2026")


def test_provider_badges_distinguish_live_cached_failed():
    assert provider_result_badge(ProviderResult("a", "A", "ok"))[0] == "Live results"
    assert provider_result_badge(ProviderResult("a", "A", "ok", from_cache=True))[0] == "Cached results"
    assert provider_result_badge(ProviderResult("a", "A", "error"))[0] == "Failed"
    assert provider_result_badge(ProviderResult("a", "A", "skipped"))[0] == "Not searched"


def test_salary_period_shown_when_stated():
    html = job_card_html(_job(salary_min=40, salary_max=60, salary_currency="USD", salary_period="hourly"))
    assert "USD 40 – 60 per hour" in html
