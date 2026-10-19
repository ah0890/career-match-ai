"""Recruitment tracking: migration of older databases, counting rules, timeline and safe automatic updates."""

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import inspect, select

from config.settings import get_settings
from src.db.engine import get_engine, session_scope
from src.db.migrations import migrate
from src.db.models import Application, ApplicationEvent, SchemaMigration
from src.tracker.recruitment import (
    NO_RESPONSE, apply_detected, current_status, interview_count, offer_count, tracking_summary,
)
from src.tracker.repository import (
    ApplicationInput, TrackerError, add_event, add_manual, correct_counts, get, record_application, set_status,
)
from src.ui.tracker_view import timeline_html
from tests.fixtures.match_factory import job

NOW = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)


@pytest.fixture
def db():
    return get_settings().database_url


def _app(**kw) -> Application:
    """An in-memory application (no database) for pure counting tests."""
    defaults = dict(title="Analyst", status="Application Submitted", applied_at=NOW - timedelta(days=2),
                    last_activity_at=NOW - timedelta(days=2), updated_at=NOW - timedelta(days=2))
    defaults.update(kw)
    app = Application(**defaults)
    app.events = []
    return app


def _event(app, kind, days_ago, source="email"):
    add_event(app, kind, occurred_at=NOW - timedelta(days=days_ago), summary=kind, source=source)


# --- migration ----------------------------------------------------------------

def test_older_databases_are_migrated_once(tmp_path):
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE applications (id INTEGER PRIMARY KEY, job_key VARCHAR(600) UNIQUE, title VARCHAR(300),
          company VARCHAR(300), location VARCHAR(300), source_name VARCHAR(100), listing_url VARCHAR(2048),
          apply_url VARCHAR(2048), description TEXT, status VARCHAR(30), match_score FLOAT,
          recommendation VARCHAR(40), applied_on DATE, next_action VARCHAR(300), next_action_on DATE, notes TEXT,
          created_at DATETIME, updated_at DATETIME);
        CREATE TABLE status_changes (id INTEGER PRIMARY KEY, application_id INTEGER REFERENCES applications(id)
          ON DELETE CASCADE, from_status VARCHAR(30), to_status VARCHAR(30), changed_at DATETIME);
        INSERT INTO applications (id, title, status, created_at, updated_at)
          VALUES (1, 'Analyst', 'Interview', '2026-10-01 09:00:00.000000', '2026-10-05 09:00:00.000000');
        INSERT INTO status_changes (application_id, from_status, to_status, changed_at) VALUES
          (1, NULL, 'Saved', '2026-10-01 09:00:00.000000'),
          (1, 'Saved', 'Applied', '2026-10-02 09:00:00.000000'),
          (1, 'Applied', 'Interview', '2026-10-05 09:00:00.000000');
    """)
    con.close()
    url = f"sqlite:///{path.as_posix()}"
    engine = get_engine(url)
    assert {"contact_email", "interviews_override", "status_set_manually_at"} <= {
        c["name"] for c in inspect(engine).get_columns("applications")}
    with session_scope(url) as s:
        app = s.get(Application, 1)
        assert app.status == "Interview Scheduled"
        assert [(h.from_status, h.to_status) for h in app.history][1:] == [
            ("Saved", "Application Submitted"), ("Application Submitted", "Interview Scheduled")]
        assert [e.kind for e in app.events] == ["Saved", "Application Submitted", "Interview Scheduled"]
        assert app.last_activity_at.date().isoformat() == "2026-10-05"
        assert [m.version for m in s.scalars(select(SchemaMigration))] == [1, 2, 3]
        assert {"cv_doc_id", "cv_revision_number"} <= {c["name"] for c in inspect(engine).get_columns("applications")}
    assert migrate(engine) == []  # running again changes nothing
    with session_scope(url) as s:
        assert len(list(s.scalars(select(ApplicationEvent)))) == 3


# --- counting -------------------------------------------------------------------

def test_invitation_and_scheduling_of_one_interview_count_once():
    app = _app(status="Interview Scheduled")
    _event(app, "Interview Invitation", 5)
    _event(app, "Interview Scheduled", 4)
    assert interview_count(app) == 1
    _event(app, "Interview Invitation", 2)  # a second round
    assert interview_count(app) == 2
    app.interviews_override = 3
    assert interview_count(app) == 3


def test_offer_count_follows_events_status_and_corrections():
    assert offer_count(_app()) == 0
    assert offer_count(_app(status="Offer Received")) == 1  # set by hand, no event
    app = _app(status="Offer Received")
    _event(app, "Offer Received", 3)
    _event(app, "Offer Received", 1)  # a revised offer
    assert offer_count(app) == 2
    app.offers_override = 1
    assert offer_count(app) == 1


def test_summary_counts_each_application_once_per_card():
    old = NOW - timedelta(days=30)
    apps = [
        _app(status="Saved", applied_at=None),  # not an application yet
        _app(),  # pending
        _app(last_activity_at=old, applied_at=old),  # no response
        _app(status="Under Review"),
        _app(status="Interview Scheduled"),
        _app(status="Offer Received"),
        _app(status="Rejected"),
    ]
    _event(apps[5], "Interview Invitation", 10)
    _event(apps[5], "Offer Received", 3)
    t = tracking_summary(apps, NOW, no_response_days=21)
    assert (t.total, t.active, t.pending, t.under_review) == (6, 5, 1, 1)
    assert (t.interviews_received, t.interviews_scheduled, t.offers, t.rejections, t.no_response) == (2, 1, 1, 1, 1)
    assert t.pending + t.no_response == 2  # never overlap
    assert current_status(apps[2], NOW, 21) == NO_RESPONSE and current_status(apps[1], NOW, 21) == "Application Submitted"


# --- automatic updates ----------------------------------------------------------

def test_detected_events_only_move_forward():
    app = _app(status="Interview Invitation")
    d = apply_detected(app, "Application Received", occurred_at=NOW, summary="Thanks for applying", confidence=0.9)
    assert not d.changed and app.status == "Interview Invitation" and app.events[-1].kind == "Application Received"
    d = apply_detected(app, "Offer Received", occurred_at=NOW, summary="Offer", confidence=0.95)
    assert d.changed and app.status == "Offer Received" and app.history[-1].to_status == "Offer Received"


def test_manual_corrections_are_never_overwritten_by_older_emails():
    app = _app(status="Under Review", status_set_manually_at=NOW)
    d = apply_detected(app, "Rejected", occurred_at=NOW - timedelta(hours=2), summary="x", confidence=0.95)
    assert not d.changed and app.status == "Under Review" and "yourself" in d.reason
    d = apply_detected(app, "Interview Invitation", occurred_at=NOW + timedelta(hours=1), summary="x", confidence=0.9)
    assert d.changed  # news after the correction still counts


def test_rejections_close_open_stages_but_not_offers_or_closed_applications():
    app = _app(status="Interview Completed")
    assert apply_detected(app, "Rejected", occurred_at=NOW, summary="x", confidence=0.9).changed
    offer = _app(status="Offer Received")
    assert not apply_detected(offer, "Rejected", occurred_at=NOW, summary="x", confidence=0.9).changed
    withdrawn = _app(status="Withdrawn")
    assert not apply_detected(withdrawn, "Offer Received", occurred_at=NOW, summary="x", confidence=0.9).changed


def test_other_communication_goes_on_the_timeline_only():
    app = _app()
    d = apply_detected(app, "Other Recruitment Communication", occurred_at=NOW, summary="Salary question",
                       confidence=0.8)
    assert not d.changed and app.status == "Application Submitted" and app.last_activity_at == NOW


# --- recording and corrections ----------------------------------------------------

def test_recording_an_email_application(db):
    j = job()
    with session_scope(db) as s:
        app = record_application(s, None, j, contact_email=" Jobs@Example.com ", subject="Application for QE")
        assert app.status == "Application Submitted" and app.contact_email == "jobs@example.com"
        assert app.application_subject == "Application for QE" and app.applied_at is not None
        assert app.events[-1].summary == "Application submitted by email to jobs@example.com"
        again = record_application(s, None, j)  # confirming twice never duplicates
        assert again.id == app.id and len(again.events) == 2
    with session_scope(db) as s, pytest.raises(TrackerError, match="valid email"):
        record_application(s, None, job(source_job_id="2"), contact_email="not an email")


def test_count_corrections_are_validated(db):
    with session_scope(db) as s:
        app_id = add_manual(s, ApplicationInput("Analyst", status="Interview Scheduled")).id
        with pytest.raises(TrackerError):
            correct_counts(s, app_id, interviews=-1, offers=None)
        correct_counts(s, app_id, interviews=2, offers=0)
        assert interview_count(get(s, app_id)) == 2
        correct_counts(s, app_id, interviews=None, offers=None)
        assert interview_count(get(s, app_id)) == 1


def test_set_status_rejects_unknown_and_legacy_names(db):
    with session_scope(db) as s:
        app_id = add_manual(s, ApplicationInput("Analyst")).id
        with pytest.raises(TrackerError):
            set_status(s, app_id, "Applied")


def test_timeline_escapes_text_and_orders_events():
    app = _app()
    _event(app, "Interview Invitation", 1)
    add_event(app, "Application Received", occurred_at=NOW - timedelta(days=3), summary="<b>Thanks</b>",
              source="email", confidence=0.91)
    html = timeline_html(app.events)
    assert "&lt;b&gt;Thanks&lt;/b&gt;" in html and "<b>Thanks" not in html
    assert html.index("Application Received") < html.index("Interview Invitation")
    assert "91% confidence" in html and "from email" in html
