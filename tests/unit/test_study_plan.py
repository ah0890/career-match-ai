"""Study plans built from job/CV gaps."""

from datetime import date

from src.interview.study import OFFICIAL_DOCS, build_study_plan, progress
from src.matching.engine import match_job
from src.matching.improvements import improvement_plan
from tests.fixtures.match_factory import DEFAULT_WEIGHTS, job, profile

DESC = ("Responsibilities\n- Coordinate internal audits against ISO 13485\n"
        "Requirements\n- Kubernetes is essential\n- Python and Minitab\n- Docker for deployments\n"
        "- Tableau is a plus\n")
TODAY = date(2026, 10, 19)


def _plan(description=DESC, interview_on=None):
    p = profile()
    r = match_job(p, job(description), DEFAULT_WEIGHTS)
    return build_study_plan(r, improvement_plan(p, r), interview_on, TODAY)


def _topic(plan, tid):
    return next(t for t in plan.topics if t.id == tid)


def test_topics_follow_gaps_in_priority_order():
    plan = _plan()
    ids = [t.id for t in plan.topics]
    assert ids[0] == "learn:Kubernetes" and _topic(plan, "learn:Kubernetes").priority == "High"
    assert _topic(plan, "learn:Docker").priority == "Medium"
    assert "example:Minitab" in ids  # listed in the CV but not shown in a role
    assert "learn:Python" not in ids and "example:Python" not in ids  # shown in experience
    assert _topic(plan, "preferred:Tableau").priority == "Low"
    assert any(i.startswith("resp:") for i in ids) and "practice" in ids
    order = {"High": 0, "Medium": 1, "Low": 2}
    assert [order[t.priority] for t in plan.topics] == sorted(order[t.priority] for t in plan.topics)


def test_links_are_official_documentation_only():
    plan = _plan()
    assert _topic(plan, "learn:Kubernetes").link == OFFICIAL_DOCS["Kubernetes"]
    assert _topic(plan, "example:Minitab").link is None  # no curated official link → none invented
    assert all(url.startswith("https://") for url in OFFICIAL_DOCS.values())


def test_effort_is_relative_not_hours():
    assert {t.effort for t in _plan().topics} <= {"Short", "Medium", "Long"}


def test_schedule_notes_use_interview_date():
    assert _plan(interview_on=date(2026, 10, 29)).days_left == 10
    assert "1 high-priority" in _plan(interview_on=date(2026, 10, 29)).schedule_note
    assert "Little time left" in _plan(interview_on=date(2026, 10, 20)).schedule_note
    assert "in the past" in _plan(interview_on=date(2026, 10, 1)).schedule_note
    assert _plan().schedule_note is None


def test_progress_counts_only_prepared_topics_in_this_plan():
    plan = _plan()
    statuses = {"learn:Kubernetes": "Prepared", "practice": "Preparing", "gone:topic": "Prepared"}
    assert progress(statuses, plan) == (1, len(plan.topics))
