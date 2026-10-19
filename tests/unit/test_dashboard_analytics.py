"""Dashboard analytics and charts, from a temporary database."""

from datetime import date, datetime, timezone

import pytest

from config.settings import RecommendationThresholds, get_settings
from src.analytics.dashboard import activity_summary, match_summary, pipeline, weekly_applications
from src.db.engine import session_scope
from src.db.models import StatusChange
from src.jobs.models import SearchQuery
from src.matching.engine import match_job
from src.matching.recommendations import Label, prioritise
from src.providers.base import ProviderResult
from src.services.history import record_search
from src.services.job_search import SearchOutcome
from src.tracker.repository import ApplicationInput, add_manual, set_status
from src.ui.charts import SERIES, pipeline_figure, score_figure, weekly_figure
from tests.fixtures.match_factory import DEFAULT_WEIGHTS, SHORT_JOB, job, profile

TODAY = date(2026, 10, 19)  # a Monday


@pytest.fixture
def url():
    return get_settings().database_url


def test_empty_database_has_no_activity(url):
    with session_scope(url) as s:
        a = activity_summary(s, TODAY)
    assert not a.has_activity and a.tracked == 0 and a.active == 0
    assert len(a.applied_per_week) == 12 and all(w.count == 0 for w in a.applied_per_week)


def test_activity_counts_searches_statuses_and_weekly_applications(url):
    record_search(url, SearchOutcome(SearchQuery(keywords="Analyst"), (ProviderResult("x", "X", "ok"),),
                                     datetime.now(timezone.utc)))
    with session_scope(url) as s:
        a = add_manual(s, ApplicationInput("Analyst")).id
        b = add_manual(s, ApplicationInput("Engineer")).id
        add_manual(s, ApplicationInput("Manager", status="Rejected"))
    with session_scope(url) as s:
        set_status(s, a, "Applied")
        set_status(s, b, "Applied")
        set_status(s, b, "Interview")
        s.add(StatusChange(application_id=a, from_status="Saved", to_status="Applied",
                           changed_at=datetime(2026, 10, 7, tzinfo=timezone.utc)))  # two weeks earlier
    with session_scope(url) as s:
        act = activity_summary(s)
        weeks = weekly_applications(s, TODAY)
    assert act.searches_30d == 1 and act.tracked == 3 and act.active == 2
    assert pipeline(act.status_counts) == [("Applied", 1), ("Interview", 1), ("Rejected", 1)]
    by_week = {w.week_start: w.count for w in weeks}
    assert by_week[date(2026, 10, 5)] == 1 and weeks[-1].week_start == TODAY


def test_match_summary_excludes_low_confidence_scores():
    p = profile()
    results = [match_job(p, job(), DEFAULT_WEIGHTS), match_job(p, job(SHORT_JOB, source_job_id="s"), DEFAULT_WEIGHTS)]
    m = match_summary(prioritise(results, RecommendationThresholds()))
    assert m.total == 2 and len(m.scores) == 1
    assert m.by_label[Label.APPLY] >= 1 and all(t.result.confidence != "Low" for t in m.top)


def test_charts_use_one_validated_series_colour_and_no_legend():
    figs = [pipeline_figure([("Saved", 2), ("Applied", 1)]), score_figure((55, 72, 90), 70, 80),
            weekly_figure(weekly_applications_stub())]
    for fig in figs:
        assert fig.layout.showlegend is False
        assert fig.data[0].marker.color == SERIES and len(fig.data) == 1
        assert "<extra></extra>" in fig.data[0].hovertemplate
    assert list(figs[0].data[0].y) == ["Applied", "Saved"]  # first stage drawn at the top


def weekly_applications_stub():
    from src.analytics.dashboard import WeekCount
    return (WeekCount(date(2026, 10, 5), 1), WeekCount(date(2026, 10, 12), 0))
