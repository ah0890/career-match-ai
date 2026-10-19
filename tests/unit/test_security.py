"""Security regression tests: injection through every HTML builder, unsafe URLs, size limits, binding."""

import re
import tomllib
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from config.settings import RecommendationThresholds, get_settings
from src.company.models import CompanyProfile, Fact, Source, Summary
from src.db.engine import session_scope
from src.db.models import Application
from src.interview.prep import build_prep_plan
from src.interview.study import StudyTopic
from src.jobs.models import JobPosting, SourceLink, safe_url
from src.matching.engine import match_job
from src.matching.recommendations import RankedMatch, recommend
from src.providers.base import ProviderResponseError
from src.providers.http import MAX_RESPONSE_BYTES, ProviderHttp
from src.ui.company_view import facts_html, profile_header_html, summary_html
from src.ui.interview_view import question_card_html, study_topic_html
from src.ui.job_cards import job_card_html
from src.ui.match_cards import comparison_html, description_html, match_card_html
from src.ui.tracker_view import application_card_html
from tests.fixtures.match_factory import DEFAULT_WEIGHTS, profile

ROOT = Path(__file__).resolve().parents[2]
PAYLOAD = '<script>alert(1)</script><img src=x onerror=alert(2)>"\'><a href="javascript:alert(3)">x</a>'
UNSAFE_URLS = ["javascript:alert(1)", "data:text/html,<script>alert(1)</script>", "vbscript:x", "file:///etc/passwd",
               "https://user:pass@evil.example.com/", "//evil.example.com", "https://", " https://a b.com"]


def _assert_inert(html: str) -> None:
    """Hostile text may appear escaped (harmless); it must never become markup, a handler or a link."""
    lowered = html.lower()
    assert "<script" not in lowered and "<img" not in lowered
    assert not re.search(r"href\s*=\s*[\"']?\s*(?:javascript|data|vbscript):", lowered)
    assert not re.search(r"<[^>]*\son\w+\s*=", lowered)  # no event handler inside any real tag


def _evil_job(**kw) -> JobPosting:
    base = dict(provider_id="himalayas", source_name="Himalayas", title=PAYLOAD, company=PAYLOAD, location=PAYLOAD,
                description=f"Requirements\n- {PAYLOAD} Python is essential\nResponsibilities\n- Lead {PAYLOAD}\n",
                salary_text=PAYLOAD, listing_url="https://himalayas.app/jobs/1",
                also_listed_on=(SourceLink(provider_id="x", source_name=PAYLOAD, listing_url="javascript:alert(1)"),))
    base.update(kw)
    return JobPosting(**base)


@pytest.mark.parametrize("url", UNSAFE_URLS)
def test_unsafe_urls_are_rejected_everywhere(url):
    assert safe_url(url) is None
    assert _evil_job(listing_url=url, apply_url=url, source_url=url).listing_url is None
    assert SourceLink(provider_id="x", source_name="X", listing_url=url).listing_url is None


def test_every_html_builder_escapes_hostile_content():
    job = _evil_job()
    p = profile()
    result = match_job(p, job, DEFAULT_WEIGHTS)
    ranked = RankedMatch(result, recommend(result, RecommendationThresholds()))
    src = Source("Wikidata", "https://www.wikidata.org/wiki/Q1", "CC0 1.0")
    company = CompanyProfile("Q1", PAYLOAD, PAYLOAD, Summary(PAYLOAD, src), (Fact(PAYLOAD, PAYLOAD, src, PAYLOAD),), (),
                             None, (), datetime.now(timezone.utc))
    outputs = [
        job_card_html(job), match_card_html(result, ranked.recommendation), comparison_html([ranked, ranked]),
        description_html(job), facts_html(company.facts, PAYLOAD), summary_html(company.summary),
        profile_header_html(company),
        study_topic_html(StudyTopic("t", PAYLOAD, PAYLOAD, "High", "Short", (PAYLOAD,), None)),
        *(question_card_html(q) for q in build_prep_plan(p, result).questions),
    ]
    for html in outputs:
        _assert_inert(html)


def test_tracker_card_rechecks_links_read_from_the_database():
    app = Application(id=1, title=PAYLOAD, company=PAYLOAD, location=None, source_name=PAYLOAD, status="Saved",
                      listing_url="javascript:alert(1)", next_action=PAYLOAD,
                      updated_at=datetime.now(timezone.utc))
    html = application_card_html(app)
    _assert_inert(html)
    assert "View listing" not in html


def test_tampered_database_rows_cannot_inject_links():
    with session_scope(get_settings().database_url) as s:
        s.add(Application(title="Analyst", status="Saved", listing_url="javascript:alert(1)"))
    with session_scope(get_settings().database_url) as s:
        app = s.query(Application).one()
        assert "javascript:" not in application_card_html(app)


def test_oversized_source_responses_are_refused():
    big = b'{"jobs": "' + b"x" * (MAX_RESPONSE_BYTES + 1) + b'"}'
    http = ProviderHttp(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=big)), sleep=lambda s: None)
    with pytest.raises(ProviderResponseError, match="more data than expected"):
        http.get_json("remotive", "https://remotive.com/api/remote-jobs")


def test_error_messages_never_contain_urls_or_credentials():
    def handler(request):
        return httpx.Response(403)
    http = ProviderHttp(transport=httpx.MockTransport(handler), sleep=lambda s: None)
    with pytest.raises(Exception) as exc:
        http.get_json("adzuna", "https://api.adzuna.com/v1/api/jobs/gb/search/1",
                      params={"app_id": "ID123", "app_key": "SECRET456"})
    assert "SECRET456" not in str(exc.value) and "ID123" not in str(exc.value) and "adzuna.com" not in str(exc.value)


def test_server_is_bound_to_this_computer_with_xsrf_protection():
    server = tomllib.loads((ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8"))["server"]
    assert server["address"] == "localhost"
    assert server["enableXsrfProtection"] is True and server["enableStaticServing"] is False


def test_secrets_are_not_exposed_by_settings(monkeypatch):
    monkeypatch.setenv("CAREERMATCH_ADZUNA_APP_KEY", "SECRET456")
    get_settings.cache_clear()
    s = get_settings()
    assert "SECRET456" not in repr(s) and "SECRET456" not in str(s.model_dump())


def test_gitignore_protects_personal_data():
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for pattern in (".env", "data/*", "*.db"):
        assert pattern in ignored


@pytest.mark.parametrize("bad", ['<a href="javascript:alert(1)">x</a>', "<script>x</script>", '<div onclick="x">',
                                 "<img src=x>", "<a href='data:text/html,x'>"])
def test_inertness_check_catches_real_injections(bad):
    with pytest.raises(AssertionError):
        _assert_inert(f"<p>safe</p>{bad}")
