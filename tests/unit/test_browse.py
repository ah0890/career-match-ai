"""Filtering, sorting, paging and comparison of ranked matches."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone

from config.settings import RecommendationThresholds
from src.jobs.models import WorkArrangement
from src.matching.browse import MatchFilter, filter_matches, page_slice, sort_matches, source_names
from src.matching.engine import match_job
from src.matching.recommendations import Label, prioritise
from src.ui.match_cards import comparison_html, description_html
from tests.fixtures.match_factory import DEFAULT_WEIGHTS, SHORT_JOB, job, profile

NOW = datetime(2026, 10, 19, tzinfo=timezone.utc)
T = RecommendationThresholds()


def _ranked():
    p = profile()
    jobs = [
        job(source_job_id="a", posted_at=NOW - timedelta(days=10), work_arrangement=WorkArrangement.REMOTE),
        job("Requirements\n- Kubernetes is essential\n- Must have FMEA\n" + "Quality work. " * 80, source_job_id="b",
            posted_at=NOW - timedelta(days=1), provider_id="jobicy", source_name="Jobicy"),
        job(SHORT_JOB, source_job_id="c"),
        job(source_job_id="d", expires_at=NOW - timedelta(days=1)),
    ]
    return prioritise([match_job(p, j, DEFAULT_WEIGHTS) for j in jobs], T, NOW)


def _ids(ms):
    return [m.result.job.source_job_id for m in ms]


def test_default_filter_hides_only_expired():
    assert sorted(_ids(filter_matches(_ranked(), MatchFilter(now=NOW)))) == ["a", "b", "c"]
    assert "d" in _ids(filter_matches(_ranked(), MatchFilter(hide_expired=False, now=NOW)))


def test_filters_by_label_score_confidence_source_arrangement_and_gaps():
    r = _ranked()
    apply_only = filter_matches(r, MatchFilter(labels=frozenset({Label.APPLY}), now=NOW))
    assert apply_only and all(m.recommendation.label is Label.APPLY for m in apply_only)
    assert "b" not in _ids(apply_only)  # essential gap → never APPLY
    assert "c" not in _ids(filter_matches(r, MatchFilter(include_low_confidence=False, now=NOW)))
    assert _ids(filter_matches(r, MatchFilter(sources=frozenset({"Jobicy"}), now=NOW))) == ["b"]
    assert _ids(filter_matches(r, MatchFilter(arrangements=frozenset({WorkArrangement.REMOTE}), now=NOW))) == ["a"]
    assert "b" not in _ids(filter_matches(r, MatchFilter(essential_gaps_ok=False, now=NOW)))
    assert all(m.result.score >= 90 for m in filter_matches(r, MatchFilter(min_score=90, now=NOW)))


def test_sorting_keeps_low_confidence_last_and_undated_jobs_after_dated():
    r = filter_matches(_ranked(), MatchFilter(now=NOW))
    assert _ids(sort_matches(r, "newest")) == ["b", "a", "c"]
    assert _ids(sort_matches(r, "score"))[-1] == "c"
    rec = sort_matches(r, "recommended")
    assert rec[0].recommendation.label is Label.APPLY and _ids(rec)[-1] == "c"


def test_page_slice_clamps_and_counts_pages():
    items = list(range(31))
    assert page_slice(items, 1, 15) == (list(range(15)), 3)
    assert page_slice(items, 9, 15) == ([30], 3)
    assert page_slice([], 1, 15) == ([], 1)


def test_source_names_are_distinct_and_sorted():
    assert source_names(_ranked()) == ["Himalayas", "Jobicy"]


def test_comparison_lists_components_gaps_and_unknowns_honestly():
    r = filter_matches(_ranked(), MatchFilter(now=NOW))[:2]
    html = comparison_html(r)
    assert html.count("<th scope=\"col\">") == 2
    assert "Required skills" in html and "Kubernetes" in html
    assert "Not provided" in html  # salary/location not invented


def test_comparison_and_description_escape_content():
    m = _ranked()[0]
    evil = replace(m, result=replace(m.result, job=job("<script>x</script>\nLine two", title="<b>T</b>")))
    assert "<script>" not in comparison_html([evil, m]) and "<b>T" not in comparison_html([evil, m])
    html = description_html(evil.result.job)
    assert "&lt;script&gt;" in html and "Line two" in html
    assert "did not provide a description" in description_html(job(""))
