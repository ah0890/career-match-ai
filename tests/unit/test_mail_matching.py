"""Matching emails to applications, with confidence and margins."""

from datetime import datetime, timedelta, timezone

from src.mail.matching import AUTO_LINK, THREAD, Candidate, match, score
from src.mail.types import MailItem

NOW = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)
EXAMPLE = Candidate(1, "Senior Quality Engineer", "Example Devices Ltd", "talent@exampledevices.com",
                    "Application for Senior Quality Engineer", NOW - timedelta(days=10))
NORTHWIND = Candidate(2, "Quality Engineering Lead", "Northwind Medical", None, None, NOW - timedelta(days=5))
CONTOSO = Candidate(3, "Supplier Quality Engineer", "Contoso", None, None, NOW - timedelta(days=5))
ALL = [EXAMPLE, NORTHWIND, CONTOSO]


def _mail(**kw) -> MailItem:
    base = dict(provider_id="m1", thread_id="t1", internet_id="<m1@example>", direction="in",
                from_address="someone@unknown.example", from_name=None, to_addresses=("alex@example.com",),
                subject="Hello", text="", sent_at=NOW)
    base.update(kw)
    return MailItem(**base)


def _match(item, threads=None, linked=None):
    return match(item, ALL, threads=threads or {}, linked_ids=linked or {})


def test_same_thread_and_direct_replies_are_near_certain():
    assert _match(_mail(thread_id="t-app"), threads={"t-app": 2}) == _match(_mail(thread_id="t-app"), threads={"t-app": 2})
    m = _match(_mail(thread_id="t-app"), threads={"t-app": 2})
    assert m.application_id == 2 and m.confidence == THREAD and m.automatic
    m = _match(_mail(thread_id="new", references=("<sent-1@mail>",)), linked={"<sent-1@mail>": 3})
    assert m.application_id == 3 and m.automatic


def test_reply_from_the_address_you_applied_to():
    m = _match(_mail(from_address="talent@exampledevices.com", subject="Your application"))
    assert m.application_id == 1 and m.automatic and "address you applied to" in m.reason


def test_company_domain_and_name_link_automatically():
    m = _match(_mail(from_address="no-reply@careers.northwind-medical.com", from_name="Northwind Medical Careers",
                     subject="Update on your application"))
    assert m.application_id == 2 and m.automatic and m.confidence >= AUTO_LINK


def test_applicant_tracking_systems_need_the_company_named():
    named = _match(_mail(from_address="no-reply@greenhouse.io", from_name="Contoso Hiring",
                         subject="Thank you for applying to Contoso", text="Supplier Quality Engineer role"))
    assert named.application_id == 3 and named.automatic
    anonymous = _match(_mail(from_address="no-reply@greenhouse.io", subject="Thank you for applying"))
    assert anonymous.application_id is None


def test_job_title_alone_never_links_automatically():
    m = _match(_mail(from_address="recruiter@agency.example", subject="Quality Engineering Lead opportunity"))
    assert not m.automatic


def test_close_calls_are_suggested_for_review_not_linked():
    twin = Candidate(4, "Quality Engineer", "Example Devices", None, None, NOW - timedelta(days=3))
    m = match(_mail(from_address="hr@exampledevices.com", subject="Your application to Example Devices"),
              [EXAMPLE, twin], threads={}, linked_ids={})
    assert m.application_id in (1, 4) and not m.automatic and m.alternatives


def test_emails_sent_before_the_application_are_ignored():
    m = _match(_mail(from_address="talent@exampledevices.com", sent_at=NOW - timedelta(days=30)))
    assert m.application_id is None


def test_freemail_domains_never_count_as_the_company():
    gmail_contact = Candidate(5, "Analyst", "Gmail Ventures", "founder@gmail.com", None, NOW - timedelta(days=1))
    conf, reason = score(_mail(from_address="friend@gmail.com"), gmail_contact)
    assert conf == 0 and reason == ""


def test_outgoing_application_emails_match_by_recipient_and_subject():
    sent = _mail(direction="out", from_address="alex@example.com", to_addresses=("talent@exampledevices.com",),
                 subject="Application for Senior Quality Engineer", sent_at=NOW - timedelta(days=10))
    m = _match(sent)
    assert m.application_id == 1 and m.automatic


def test_unrelated_email_matches_nothing():
    assert _match(_mail(subject="Lunch?", text="Free on Friday?")).application_id is None
