"""Email synchronisation against a fake Gmail / Graph / OAuth service. No network, no real mailbox."""

from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from sqlalchemy import select

from config.settings import get_settings
from src.db.engine import session_scope
from src.db.models import ApplicationEvent, MailAccount, MailMessage, SyncRun
from src.mail import oauth, review, vault
from src.mail.__main__ import main as cli
from src.mail.providers import MailError, MailHttp, OutlookProvider
from src.mail.sync import build_provider, connect_account, disconnect, due_for_auto_sync, sync_account
from src.tracker.repository import ApplicationInput, TrackerError, add_manual, get, list_applications
from tests.fixtures.mailbox import ME, FakeMail, FakeMailbox, token

T0 = datetime.now(timezone.utc) - timedelta(days=5)


@pytest.fixture
def settings(monkeypatch):
    monkeypatch.setenv("CAREERMATCH_GMAIL_CLIENT_ID", "client-id.apps.example")
    monkeypatch.setenv("CAREERMATCH_GMAIL_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("CAREERMATCH_OUTLOOK_CLIENT_ID", "outlook-client")
    get_settings.cache_clear()
    return get_settings()


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    slept = []
    monkeypatch.setattr("src.mail.providers.time.sleep", slept.append)
    return slept


def _applications(url):
    with session_scope(url) as s:
        a = add_manual(s, ApplicationInput("Senior Quality Engineer", "Example Devices Ltd",
                                           status="Application Submitted", contact_email="talent@exampledevices.com",
                                           application_subject="Application for Senior Quality Engineer",
                                           applied_at=T0)).id
        b = add_manual(s, ApplicationInput("Data Analyst", "Northwind Medical", status="Application Submitted",
                                           applied_at=T0)).id
        for app_id in (a, b):  # the user recorded these before the emails below
            get(s, app_id).status_set_manually_at = T0 - timedelta(hours=1)
    return a, b


def _mailbox() -> FakeMailbox:
    h = timedelta(hours=1)
    return FakeMailbox(messages=[
        FakeMail("m6", "t1", "talent@exampledevices.com", ME, "Re: Application for Senior Quality Engineer",
                 "Great news! We would like to invite you to an interview next week. Please share your availability.",
                 T0 + 30 * h, in_reply_to="<out1@mail>"),
        FakeMail("m1", "t1", ME, "talent@exampledevices.com", "Application for Senior Quality Engineer",
                 "Dear hiring team, please find my CV attached.", T0 + h, sent=True, message_id="<out1@mail>"),
        FakeMail("m2", "t1", "talent@exampledevices.com", ME, "Re: Application for Senior Quality Engineer",
                 "Thank you for your application. We have received your application.\n\nOn Mon Alex wrote:\n> CV",
                 T0 + 5 * h),
        FakeMail("m3", "t3", "no-reply@greenhouse.io", ME, "Interview invitation – Data Analyst",
                 "Hi Alex, we'd like to invite you to an interview for the Data Analyst role at Northwind Medical.",
                 T0 + 20 * h, sender_name="Northwind Medical Hiring"),
        FakeMail("m4", "t4", "alerts@jobs.example", ME, "10 new jobs matching Quality Engineer",
                 "Recommended jobs for you. Unsubscribe.", T0 + 21 * h),
        FakeMail("m5", "t5", "recruiter@agency.example", ME, "Quality role",
                 "Thank you for your application to the Quality Engineer role. A recruiter will be in touch.",
                 T0 + 22 * h),
        FakeMail("m7", "t7", "friend@example.org", ME, "Lunch?", "Free on Friday?", T0 + 23 * h),
    ])


def _connect(url, box, settings, provider="gmail"):
    with box.client() as client, session_scope(url) as s:
        return connect_account(s, provider, token(), client).id


def _sync(url, box, settings, **kw):
    with box.client() as client, session_scope(url) as s:
        account = s.get(MailAccount, 1)
        run = sync_account(s, account, build_provider(account, settings, client), settings, **kw)
        return run.status, run.new, run.matched, run.review, run.error


# --- full journey -----------------------------------------------------------------

def test_sync_links_classifies_and_updates_applications(settings):
    url = settings.database_url
    a, b = _applications(url)
    box = _mailbox()
    _connect(url, box, settings)
    status, new, matched, to_review, error = _sync(url, box, settings)
    assert (status, error) == ("ok", None)
    assert (new, matched, to_review) == (7, 4, 1)
    with session_scope(url) as s:
        app_a, app_b = get(s, a), get(s, b)
        assert app_a.status == "Interview Invitation" and app_b.status == "Interview Invitation"
        kinds_a = [(e.kind, e.source) for e in app_a.events]
        assert ("Application Received", "email") in kinds_a and ("Interview Invitation", "email") in kinds_a
        assert all(e.message_id is not None for e in app_a.events if e.source == "email")
        rows = {m.provider_id: m for m in s.scalars(select(MailMessage))}
        assert rows["m1"].relevance == "matched" and rows["m1"].application_id == a  # the outgoing application
        assert rows["m4"].relevance == "unrelated" and rows["m4"].subject is None and rows["m4"].snippet is None
        assert rows["m7"].relevance == "unrelated" and rows["m7"].from_address is None
        assert rows["m5"].relevance == "review" and rows["m5"].application_id is None
        assert "On Mon Alex wrote" not in (rows["m2"].snippet or "")  # quoted text is not kept
        account = s.get(MailAccount, 1)
        assert account.sync_status == "ok" and account.last_sync_at is not None
    query = box.queries[0]
    assert "after:" in query and '"Example Devices Ltd"' in query and "from:greenhouse.io" in query
    assert "from:talent@exampledevices.com" in query


def test_a_second_sync_never_processes_an_email_twice(settings):
    url = settings.database_url
    _applications(url)
    box = _mailbox()
    _connect(url, box, settings)
    _sync(url, box, settings)
    fetched_first = list(box.fetched)
    assert _sync(url, box, settings)[1] == 0  # nothing new
    assert box.fetched == fetched_first  # nothing downloaded again
    with session_scope(url) as s:
        assert len(list(s.scalars(select(MailMessage)))) == 7
        assert len(list(s.scalars(select(ApplicationEvent).where(ApplicationEvent.source == "email")))) == 3
        assert len(list_applications(s)) == 2  # no duplicate applications


def test_reconnecting_the_same_mailbox_updates_it(settings):
    url = settings.database_url
    box = _mailbox()
    _connect(url, box, settings)
    _connect(url, box, settings)
    with session_scope(url) as s:
        [account] = s.scalars(select(MailAccount))
        assert account.address == ME and "access-0" not in account.token_ciphertext
        assert vault.decrypt(account.token_ciphertext)["refresh_token"] == "refresh-1"


# --- failures ---------------------------------------------------------------------

def test_expired_access_token_is_refreshed_and_saved(settings):
    url = settings.database_url
    box = _mailbox()
    _connect(url, box, settings)
    box.unauthorized_once = True
    assert _sync(url, box, settings)[0] == "ok"
    assert [c["grant_type"] for c in box.token_calls] == ["refresh_token"]
    assert box.token_calls[0]["client_secret"] == "client-secret"
    with session_scope(url) as s:
        assert vault.decrypt(s.get(MailAccount, 1).token_ciphertext)["access_token"] == "access-1"


def test_revoked_access_asks_to_reconnect_and_keeps_the_sync_window(settings):
    url = settings.database_url
    box = _mailbox()
    _connect(url, box, settings)
    box.unauthorized_once, box.fail_refresh = True, True
    status, *_, error = _sync(url, box, settings)
    assert status == "reconnect" and "Reconnect" in error
    with session_scope(url) as s:
        account = s.get(MailAccount, 1)
        assert account.sync_status == "reconnect" and account.last_sync_at is None
        assert not due_for_auto_sync(account, settings)  # no point retrying until reconnected


def test_rate_limits_are_retried_after_the_requested_wait(settings, no_sleep):
    url = settings.database_url
    box = _mailbox()
    _connect(url, box, settings)
    box.statuses = [429]
    assert _sync(url, box, settings)[0] == "ok"
    assert no_sleep == [2.0]


def test_a_failing_service_is_reported_and_retried_next_time(settings):
    url = settings.database_url
    _applications(url)
    box = _mailbox()
    _connect(url, box, settings)
    box.statuses = [503, 503, 503]
    status, *_, error = _sync(url, box, settings)
    assert status == "error" and "503" in error and "http" not in error.lower().replace("http 503", "")
    assert _sync(url, box, settings)[0] == "ok"  # next sync covers the same window
    with session_scope(url) as s:
        runs = [r.status for r in s.scalars(select(SyncRun).order_by(SyncRun.id))]
        assert runs == ["error", "ok"]


def test_offline_mode_blocks_sync(monkeypatch, settings):
    from src.mail.sync import http_client
    monkeypatch.setenv("CAREERMATCH_OFFLINE_MODE", "true")
    get_settings.cache_clear()
    with pytest.raises(MailError, match="Offline mode"):
        http_client(get_settings())


def test_auto_sync_timing(settings):
    account = MailAccount(provider="gmail", address=ME, token_ciphertext="x", scopes="", sync_status="ok")
    assert due_for_auto_sync(account, settings)
    account.last_sync_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    assert not due_for_auto_sync(account, settings)
    account.last_sync_at -= timedelta(hours=1)
    assert due_for_auto_sync(account, settings)


# --- Outlook ------------------------------------------------------------------------

def test_outlook_pages_threads_and_direction(settings):
    box = _mailbox()
    box.page_size = 3
    with box.client() as client:
        http = MailHttp(client, lambda: "t", lambda: "t")
        provider = OutlookProvider(http, ME)
        assert provider.profile_address() == ME
        ids = list(provider.message_ids(T0, [], [], 100))
        assert len(ids) == 7
        sent = provider.message("m1")
        assert sent.direction == "out" and sent.thread_id == "t1" and sent.web_link == "https://outlook.example/m1"
        reply = provider.message("m2")
        assert reply.direction == "in" and "received your application" in reply.text


def test_outlook_sync_end_to_end(settings):
    url = settings.database_url
    a, _ = _applications(url)
    box = _mailbox()
    _connect(url, box, settings, provider="outlook")
    assert _sync(url, box, settings)[0] == "ok"
    with session_scope(url) as s:
        assert get(s, a).status == "Interview Invitation"


# --- OAuth ------------------------------------------------------------------------

def test_loopback_flow_uses_pkce_and_checks_state(settings):
    cid, _ = oauth.client_credentials(oauth.GMAIL, settings)
    flow = oauth.LoopbackFlow(oauth.GMAIL, cid)
    url = flow.start(timeout_s=10)
    params = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
    assert params["code_challenge_method"] == "S256" and params["scope"].endswith("gmail.readonly")
    assert params["redirect_uri"].startswith("http://127.0.0.1:") and params["access_type"] == "offline"
    assert httpx.get(flow.redirect_uri, params={"state": "forged", "code": "evil"}).status_code == 400
    assert not flow.finished
    assert httpx.get(flow.redirect_uri, params={"state": params["state"], "code": "good"}).status_code == 200
    assert flow.code == "good"
    box = FakeMailbox()
    with box.client() as client:
        tok = oauth.exchange_code(flow, "client-secret", client)
    assert tok["refresh_token"] and box.token_calls[0]["code_verifier"] == flow.verifier


def test_missing_app_registration_is_explained(monkeypatch):
    with pytest.raises(oauth.OAuthError, match="CAREERMATCH_GMAIL_CLIENT_ID"):
        oauth.client_credentials(oauth.GMAIL, get_settings())


# --- vault ----------------------------------------------------------------------------

def test_tokens_are_encrypted_and_unreadable_with_another_key(monkeypatch, tmp_path):
    secret = {"access_token": "very-secret-access", "refresh_token": "very-secret-refresh"}
    ciphertext = vault.encrypt(secret)
    assert "very-secret" not in ciphertext and vault.decrypt(ciphertext) == secret
    monkeypatch.setattr(vault, "KEY_FILE", tmp_path / "other_key")
    with pytest.raises(vault.VaultError):
        vault.decrypt(ciphertext)


# --- review & disconnect -----------------------------------------------------------------

def _synced(settings):
    url = settings.database_url
    a, b = _applications(url)
    box = _mailbox()
    _connect(url, box, settings)
    _sync(url, box, settings)
    with session_scope(url) as s:
        ids = {m.provider_id: m.id for m in s.scalars(select(MailMessage))}
    return url, a, b, ids, box


def test_review_confirm_and_create(settings):
    url, a, b, ids, _ = _synced(settings)
    with session_scope(url) as s:
        assert [m.provider_id for m in review.review_queue(s)] == ["m5"]
        app = review.create_application(s, ids["m5"], "Quality Engineer", "Agency Example", "Application Received")
        assert app.contact_email == "recruiter@agency.example" and app.status == "Application Received"
        assert review.review_queue(s) == []
        assert s.get(MailMessage, ids["m5"]).user_confirmed


def test_unlink_and_dismiss_remove_events_and_content(settings):
    url, a, b, ids, box = _synced(settings)
    with session_scope(url) as s:
        review.unlink(s, ids["m3"])
        assert not [e for e in get(s, b).events if e.source == "email"]
        assert get(s, b).status == "Interview Invitation"  # the status is left for the user to correct
        review.dismiss(s, ids["m3"])
        row = s.get(MailMessage, ids["m3"])
        assert row.relevance == "dismissed" and row.subject is None and row.snippet is None
    _sync(url, box, settings)  # a later sync never brings a corrected email back
    with session_scope(url) as s:
        assert s.get(MailMessage, ids["m3"]).relevance == "dismissed"


def test_relinking_moves_the_event_to_the_right_application(settings):
    url, a, b, ids, _ = _synced(settings)
    with session_scope(url) as s:
        review.confirm(s, ids["m3"], a, "Interview Scheduled")
        assert any(e.kind == "Interview Scheduled" for e in get(s, a).events)
        assert not [e for e in get(s, b).events if e.source == "email"]
        with pytest.raises(TrackerError):
            review.confirm(s, ids["m3"], a, "Hired")


@pytest.mark.parametrize("delete_history", [True, False])
def test_disconnect_removes_tokens_and_messages(settings, delete_history):
    url, a, *_ = _synced(settings)
    with session_scope(url) as s:
        disconnect(s, 1, delete_email_history=delete_history, client=None)
    with session_scope(url) as s:
        assert s.scalars(select(MailAccount)).first() is None and s.scalars(select(MailMessage)).first() is None
        email_events = [e for e in get(s, a).events if e.source == "email"]
        assert bool(email_events) is (not delete_history)


def test_cli(settings, capsys):
    assert cli(["x"]) == 2
    assert cli(["x", "sync"]) == 0 and "No mailbox is connected" in capsys.readouterr().out
