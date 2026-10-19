"""Email classification on realistic, synthetic recruitment emails."""

import pytest

from src.mail.classify import HIGH_IMPACT_THRESHOLD, classify, strip_quoted

CASES = [
    # (subject, body, expected kind)
    ("Thank you for applying to Example Devices",
     "Hi Alex,\n\nThank you for your application for the Senior Quality Engineer role. Our team will review "
     "your application and get back to you.", "Application Received"),
    ("Application received – Senior Quality Engineer",
     "We have received your application and it has been forwarded to the hiring manager.", "Application Received"),
    ("Your application status",
     "Your application is currently under review by the hiring team. We will be in touch soon.", "Under Review"),
    ("Next steps: online assessment",
     "As the next stage, please complete the online assessment on HackerRank within 5 days.", "Assessment"),
    ("Take-home exercise",
     "Thanks for your time. We'd like you to do a take-home assignment before the interview.", "Assessment"),
    ("Interview invitation – Senior Quality Engineer",
     "We were impressed by your background and would like to invite you to a first-round interview. "
     "Please share your availability for an interview next week.", "Interview Invitation"),
    ("Let's talk!",
     "Great news — we'd like to move you forward to the next stage, an interview with our QA lead. "
     "Book a time here: https://calendly.com/example/qa", "Interview Invitation"),
    ("Invitation: Interview with Alex Example @ Thu 23 Oct 2026 10am - 11am (BST)",
     "Example Devices has invited you to this event.", "Interview Scheduled"),
    ("Interview confirmation",
     "This is to confirm your interview on Thursday at 10:00. The interview is confirmed with Sam and Jo.",
     "Interview Scheduled"),
    ("Offer of employment",
     "Dear Alex,\n\nWe are delighted to offer you the position of Senior Quality Engineer. Your offer letter "
     "is attached.", "Offer Received"),
    ("Your application to Example Devices",
     "Thank you for your interest. Unfortunately, after careful consideration we have decided to move forward "
     "with other candidates. We wish you the best of luck in your job search.", "Rejected"),
    ("Senior Quality Engineer",
     "We regret to inform you that your application was unsuccessful on this occasion.", "Rejected"),
    ("Update on your application",
     "Unfortunately we are unable to offer you the position at this time.", "Rejected"),
    ("Quick question about your application",
     "Could you tell us your notice period and salary expectations for the role? Our recruiter will call.",
     "Other Recruitment Communication"),
]


@pytest.mark.parametrize("subject, body, kind", CASES, ids=[c[2] + ":" + c[0][:20] for c in CASES])
def test_recruitment_emails_are_classified(subject, body, kind):
    result = classify(subject, body)
    assert result.kind == kind, result


@pytest.mark.parametrize("subject, body", [
    ("10 new jobs matching Quality Engineer", "Recommended jobs for you: Quality Engineer at Example. Unsubscribe."),
    ("Your weekly digest", "Jobs you may be interested in this week."),
    ("Lunch on Friday?", "Are you free for lunch on Friday? Same place as last time."),
    ("Invoice #1042", "Please find attached the invoice for October."),
])
def test_job_alerts_and_personal_email_are_not_recruitment(subject, body):
    assert classify(subject, body).kind is None


def test_clear_rejections_and_offers_are_confident_enough_to_apply():
    rejection = classify("Update", "We regret to inform you that we have decided to proceed with other candidates.")
    offer = classify("Offer", "We are pleased to offer you the role. Please find the offer letter attached.")
    assert rejection.confidence >= HIGH_IMPACT_THRESHOLD and rejection.auto_apply
    assert offer.confidence >= HIGH_IMPACT_THRESHOLD and offer.auto_apply


def test_a_lone_unfortunately_is_not_enough_to_reject():
    result = classify("Re: availability", "Unfortunately I am out of the office on Monday.")
    assert result.kind != "Rejected" or not result.auto_apply


def test_mixed_signals_go_to_review():
    result = classify("Update", "We regret to inform you that the position has been filled. However, we would "
                                "like to offer you a different role in our team.")
    assert result.kind in ("Rejected", "Offer Received") and not result.auto_apply
    assert "also looks like" in result.reason


def test_an_interview_invitation_survives_an_unrelated_unfortunately():
    result = classify("Update", "Unfortunately the original role is on hold, but we would like to invite you to an "
                                "interview for a different team.")
    assert result.kind == "Interview Invitation" and result.auto_apply


def test_quoted_application_text_never_decides_the_result():
    body = ("Thanks Alex, we have received your application.\n\nOn Mon, 6 Oct 2026 at 09:00 Alex Example "
            "<alex@example.com> wrote:\n> I would love an interview and I hope you will offer me the role.\n"
            "> We are delighted to offer you nothing — this is quoted text.")
    assert strip_quoted(body).strip() == "Thanks Alex, we have received your application."
    assert classify("Re: Application for Senior Quality Engineer", body).kind == "Application Received"


def test_a_call_without_interview_wording_is_less_certain():
    certain = classify("Interview", "We'd like to invite you to an interview next week.")
    vague = classify("Catch up", "We'd like to invite you to a call next week.")
    assert vague.confidence < certain.confidence


def test_reason_explains_the_match():
    result = classify("Offer", "We would like to offer you the role.")
    assert "offer you" in result.reason.lower()
