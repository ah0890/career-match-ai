"""Application tracker repository and views (temporary SQLite database per test)."""

from datetime import date, timedelta

import pytest

from config.settings import RecommendationThresholds, get_settings
from src.db.engine import session_scope
from src.matching.engine import match_job
from src.matching.recommendations import RankedMatch, recommend
from src.tracker.repository import (
    ApplicationInput, TrackerError, add_manual, delete, due_actions, find_by_job, list_applications, save_job,
    set_status, set_study_status, status_counts, study_statuses, update_details,
)
from src.ui.tracker_view import application_card_html, follow_up_label
from tests.fixtures.match_factory import DEFAULT_WEIGHTS, job, profile

TODAY = date(2026, 10, 19)


@pytest.fixture
def db():
    return get_settings().database_url


def _ranked(j):
    r = match_job(profile(), j, DEFAULT_WEIGHTS)
    return RankedMatch(r, recommend(r, RecommendationThresholds()))


def test_save_job_snapshots_match_and_never_duplicates(db):
    j = job()
    with session_scope(db) as s:
        app, created = save_job(s, _ranked(j), j)
        assert created and app.status == "Saved" and app.match_score == _ranked(j).result.score
        assert app.recommendation == "APPLY" and app.listing_url == j.listing_url
        again, created_again = save_job(s, _ranked(j), j)
        assert not created_again and again.id == app.id
    with session_scope(db) as s:
        assert len(list_applications(s)) == 1 and find_by_job(s, j.key) is not None


def test_manual_entries_are_validated(db):
    with session_scope(db) as s:
        with pytest.raises(TrackerError, match="job title"):
            add_manual(s, ApplicationInput(" "))
        with pytest.raises(TrackerError, match="http"):
            add_manual(s, ApplicationInput("Analyst", listing_url="javascript:alert(1)"))
        with pytest.raises(TrackerError, match="Unknown status"):
            add_manual(s, ApplicationInput("Analyst", status="Hired"))
        app = add_manual(s, ApplicationInput("  Data   Analyst ", "Example Ltd", listing_url="https://jobs.example.com/1"))
        assert app.title == "Data Analyst" and app.source_name == "Added manually" and app.job_key is None


def test_status_changes_are_recorded_and_applied_date_set(db):
    with session_scope(db) as s:
        app_id = add_manual(s, ApplicationInput("Analyst")).id
    with session_scope(db) as s:
        set_status(s, app_id, "Application Submitted", today=TODAY)
        set_status(s, app_id, "Application Submitted", today=TODAY)  # no-op: same status
        set_status(s, app_id, "Interview Scheduled")
    with session_scope(db) as s:
        app = list_applications(s)[0]
        assert app.applied_on == TODAY and app.applied_at is not None
        assert [(h.from_status, h.to_status) for h in app.history] == [
            (None, "Saved"), ("Saved", "Application Submitted"), ("Application Submitted", "Interview Scheduled")]
        assert [e.kind for e in app.events] == ["Saved", "Application Submitted", "Interview Scheduled"]
        assert app.status_set_manually_at is not None and app.last_activity_at is not None
        assert status_counts(s)["Interview Scheduled"] == 1 and status_counts(s)["Offer Received"] == 0


def test_details_follow_ups_and_delete_cascade(db):
    with session_scope(db) as s:
        a = add_manual(s, ApplicationInput("Analyst")).id
        b = add_manual(s, ApplicationInput("Engineer")).id
        c = add_manual(s, ApplicationInput("Manager", status="Rejected")).id
    with session_scope(db) as s:
        update_details(s, a, notes="  Spoke to recruiter ", next_action="Send portfolio",
                       next_action_on=TODAY - timedelta(days=1), applied_on=None)
        update_details(s, b, notes=None, next_action=None, next_action_on=TODAY + timedelta(days=30), applied_on=None)
        update_details(s, c, notes=None, next_action="x", next_action_on=TODAY, applied_on=None)
    with session_scope(db) as s:
        due = due_actions(s, TODAY)
        assert [d.title for d in due] == ["Analyst"]  # far-future and closed applications excluded
        assert due[0].notes == "Spoke to recruiter"
        delete(s, a)
    with session_scope(db) as s:
        assert {x.title for x in list_applications(s)} == {"Engineer", "Manager"}
        with pytest.raises(TrackerError):
            delete(s, a)


def test_study_progress_is_upserted(db):
    with session_scope(db) as s:
        set_study_status(s, "job:1", "learn:SQL", "Preparing")
    with session_scope(db) as s:
        set_study_status(s, "job:1", "learn:SQL", "Prepared")
    with session_scope(db) as s:
        assert study_statuses(s, "job:1") == {"learn:SQL": "Prepared"}
        assert study_statuses(s, "job:2") == {}


def test_card_shows_status_follow_up_and_escapes(db):
    with session_scope(db) as s:
        app = add_manual(s, ApplicationInput("<b>Evil</b>", "<script>x</script>", listing_url="https://jobs.example.com/1"))
        update_details(s, app.id, notes=None, next_action="Call <i>", next_action_on=TODAY - timedelta(days=2),
                       applied_on=None)
    html = application_card_html(app, TODAY)
    assert "<b>Evil" not in html and "<script>" not in html and "<i>" not in html
    assert "Follow-up overdue by 2 day(s)" in html and 'href="https://jobs.example.com/1"' in html
    assert follow_up_label(app, TODAY - timedelta(days=2)) == ("Follow-up due today", "warning")
    assert follow_up_label(app, TODAY - timedelta(days=10)) == ("Follow-up in 8 day(s)", "info")
