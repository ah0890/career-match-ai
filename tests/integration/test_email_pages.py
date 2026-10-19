"""Email Tracking page and the tracker's email tab, rendered headlessly with synced (fake) email."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from streamlit.testing.v1 import AppTest

from config.settings import get_settings
from src.db.engine import session_scope
from src.db.models import MailAccount, MailMessage
from tests.unit.test_mail_sync import _applications, _connect, _mailbox, _sync


def _render(module: str) -> AppTest:
    script = (f"from src.ui.theme import apply_theme\napply_theme()\n"
              f"from src.pages import {module}\n{module}.render()\n")
    return AppTest.from_string(script, default_timeout=30).run()


def _text(at: AppTest) -> str:
    parts = [m.value for m in at.markdown] + [c.value for c in at.caption]
    parts += [str(h.proto.body) for h in at.get("html")]
    return "\n".join(parts)


@pytest.fixture
def synced(monkeypatch):
    monkeypatch.setenv("CAREERMATCH_GMAIL_CLIENT_ID", "client-id.apps.example")
    monkeypatch.setenv("CAREERMATCH_GMAIL_CLIENT_SECRET", "client-secret")
    get_settings.cache_clear()
    settings = get_settings()
    a, b = _applications(settings.database_url)
    box = _mailbox()
    _connect(settings.database_url, box, settings)
    _sync(settings.database_url, box, settings)
    return a, b


def test_without_a_mailbox_the_page_explains_setup():
    at = _render("email_tracking")
    assert not at.exception
    text = _text(at)
    assert "No mailbox connected" in text and "Read-only" in text
    connect = next(b for b in at.button if b.label == "Connect Gmail")
    assert connect.disabled  # no app registration in .env
    assert any(e.label == "Set up email access (one time)" for e in at.expander)


def test_review_queue_confirms_into_the_tracker(synced):
    a, _ = synced
    at = _render("email_tracking")
    assert not at.exception
    text = _text(at)
    assert "alex@example.com" in text and "Needs your review (1)" in text and "Quality role" in text
    with session_scope(get_settings().database_url) as s:
        msg_id = s.scalar(select(MailMessage.id).where(MailMessage.provider_id == "m5"))
    at.selectbox(key=f"et_app_{msg_id}").set_value(a)
    at.selectbox(key=f"et_kind_{msg_id}").set_value("Other Recruitment Communication").run()
    at.button(key=f"et_ok_{msg_id}").click().run()
    assert not at.exception
    assert "Needs your review (0)" in _text(at)
    with session_scope(get_settings().database_url) as s:
        row = s.get(MailMessage, msg_id)
        assert row.application_id == a and row.user_confirmed


def test_dismissing_removes_the_email_content(synced):
    at = _render("email_tracking")
    with session_scope(get_settings().database_url) as s:
        msg_id = s.scalar(select(MailMessage.id).where(MailMessage.provider_id == "m5"))
    at.button(key=f"et_no_{msg_id}").click().run()
    with session_scope(get_settings().database_url) as s:
        assert s.get(MailMessage, msg_id).subject is None


def test_tracker_shows_linked_emails_and_can_unlink(synced):
    _, b = synced
    script = ("import streamlit as st\nfrom src.ui.theme import apply_theme\napply_theme()\n"
              f"st.session_state.setdefault('at_selected', {b})\n"
              "from src.pages import application_tracker\napplication_tracker.render()\n")
    at = AppTest.from_string(script, default_timeout=30).run()
    assert not at.exception
    assert "Interview invitation – Data Analyst" in _text(at)
    assert list(at.dataframe[0].value["Latest reply"])  # the table shows the latest reply
    with session_scope(get_settings().database_url) as s:
        msg_id = s.scalar(select(MailMessage.id).where(MailMessage.provider_id == "m3"))
    at.button(key=f"at_munlink_{msg_id}").click().run()
    assert not at.exception
    with session_scope(get_settings().database_url) as s:
        assert s.get(MailMessage, msg_id).relevance == "review"


def test_disconnect_from_the_page(synced):
    at = _render("email_tracking")
    at.checkbox(key="et_drop_1").check()
    at.button(key="et_disconnect_1").click().run()
    assert not at.exception
    with session_scope(get_settings().database_url) as s:
        assert s.scalars(select(MailAccount)).first() is None
    assert "No mailbox connected" in _text(at)
