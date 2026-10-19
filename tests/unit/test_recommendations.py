"""Recommendation labels, reasons and suggested actions."""

from datetime import datetime, timedelta, timezone

import pytest

from config.settings import RecommendationThresholds
from src.matching.engine import match_job
from src.matching.recommendations import Label, prioritise, recommend
from src.ui.match_cards import match_summary_html
from tests.fixtures.match_factory import DEFAULT_WEIGHTS, SHORT_JOB, job, profile

T = RecommendationThresholds(apply=80, improve=70)
NOW = datetime(2026, 10, 19, tzinfo=timezone.utc)


def _with_score(result, score):
    from dataclasses import replace
    return replace(result, score=score)


@pytest.mark.parametrize("score, label", [(95, Label.APPLY), (80, Label.APPLY), (79, Label.APPLY_AFTER_IMPROVEMENT),
                                          (70, Label.APPLY_AFTER_IMPROVEMENT), (69, Label.DONT_PRIORITIZE)])
def test_labels_follow_configured_thresholds(score, label):
    base = match_job(profile(), job("Requirements\n- Python and SQL\n"), DEFAULT_WEIGHTS)
    rec = recommend(_with_score(base, score), T, NOW)
    assert rec.label is label
    assert str(score) in rec.reasons[0]


def test_custom_thresholds_are_respected():
    base = _with_score(match_job(profile(), job("Requirements\n- Python and SQL\n"), DEFAULT_WEIGHTS), 65)
    assert recommend(base, RecommendationThresholds(apply=60, improve=50), NOW).label is Label.APPLY


def test_essential_gap_is_never_apply():
    r = match_job(profile(), job("Requirements\n- Must have FMEA and SPC\n- Kubernetes is essential\n- Minitab\n"),
                  DEFAULT_WEIGHTS)
    rec = recommend(_with_score(r, 95), T, NOW)
    assert rec.label is Label.APPLY_AFTER_IMPROVEMENT
    assert any("Kubernetes" in reason for reason in rec.reasons)
    assert rec.actions[0].priority == "High" and "Kubernetes" in rec.actions[0].title
    assert "if you have it" in rec.actions[0].title


def test_expired_listing_is_not_prioritised():
    r = match_job(profile(), job(expires_at=NOW - timedelta(days=2)), DEFAULT_WEIGHTS)
    rec = recommend(_with_score(r, 95), T, NOW)
    assert rec.label is Label.DONT_PRIORITIZE and rec.headline == "This listing has expired."


def test_stale_and_low_confidence_add_caveats_without_changing_label():
    r = match_job(profile(), job(SHORT_JOB, posted_at=NOW - timedelta(days=60)), DEFAULT_WEIGHTS)
    rec = recommend(_with_score(r, 90), T, NOW)
    assert rec.label is Label.APPLY
    assert any("60 days ago" in c for c in rec.caveats)
    assert any("limited information" in c for c in rec.caveats)


def test_actions_never_invent_experience():
    r = match_job(profile(), job(), DEFAULT_WEIGHTS)
    rec = recommend(r, T, NOW)
    text = " ".join(f"{a.title} {a.detail}" for a in rec.actions)
    assert "ISO 13485" in text and "If you have used any of them" in text
    assert "Leave out anything you have not done" in text


def test_years_gap_action_is_honest():
    r = match_job(profile(), job("Requirements\n- 20+ years of experience in quality engineering\n"), DEFAULT_WEIGHTS)
    rec = recommend(r, T, NOW)
    assert any("Editing your CV cannot change this" in a.detail for a in rec.actions)


def test_check_yourself_items_become_caveats():
    rec = recommend(match_job(profile(), job(), DEFAULT_WEIGHTS), T, NOW)
    assert any("Right to work" in c for c in rec.caveats)


def test_prioritise_orders_by_label_then_score_with_low_confidence_last():
    detailed = match_job(profile(), job(), DEFAULT_WEIGHTS)
    gap = match_job(profile(), job("Requirements\n- Must have FMEA\n- Kubernetes is essential\n" + "Quality work. " * 80,
                                   source_job_id="gap"), DEFAULT_WEIGHTS)
    short = match_job(profile(), job(SHORT_JOB, source_job_id="short"), DEFAULT_WEIGHTS)
    ranked = prioritise([short, _with_score(gap, 99), _with_score(detailed, 85)], T, NOW)
    assert [m.result.job.source_job_id for m in ranked] == ["Senior Quality Engineer", "gap", "short"]


def test_summary_shows_label_and_headline():
    r = match_job(profile(), job(), DEFAULT_WEIGHTS)
    html = match_summary_html(r, recommend(_with_score(r, 90), T, NOW))
    assert "APPLY" in html and "worth applying" in html
    assert "DON&#x27;T" not in html
