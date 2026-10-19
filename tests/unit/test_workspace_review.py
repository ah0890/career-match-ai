"""CV review, approval workflow, questions, job tailoring, PDF/DOCX generation and the optional Claude provider."""

import io
from types import SimpleNamespace

import pymupdf as fitz
import pytest
from docx import Document
from pydantic import SecretStr

from config.settings import get_settings
from src.db.engine import session_scope
from src.tracker.repository import ApplicationInput, add_manual
from src.workspace import ai, approval, exports
from src.workspace import repository as repo
from src.workspace.importer import import_text
from src.workspace.render import (
    professional_filename, render_docx, render_pdf, validate_docx, validate_pdf,
)
from src.workspace.review import past_tense, review
from src.workspace.style import FormatSettings
from src.workspace.tailoring import job_posting, score, tailor
from tests.fixtures.cv_factory import make_text_pdf
from tests.fixtures.match_factory import QUALITY_CV, QUALITY_JOB

MESSY = """Sam Sample
sam@example.com

EXPERIENCE
Project Engineer — Example Ltd — January 2020 - Present
- I was responsible for managing  the  budget for three projects
- Responsible for coordinating suppliers in order to reduce delays.
- Helped with testing new equipment
- Utilized SAP on a daily basis.
- Prepared managment reports
Engineer — Sample Co — 03/2016 to 12/2019
- Managed the site team
- Managed the site team

SKILLS
SAP, Excel, SAP
"""


@pytest.fixture
def db():
    return get_settings().database_url


def _revised(db, text=MESSY):
    """A Revised Master CV made from ``text`` (the original master stays untouched)."""
    with session_scope(db) as s:
        source = repo.import_source(s, "cv.pdf", make_text_pdf(), max_bytes=5_000_000, ocr_text=text)
        master = repo.create_master(s, source)
        return master.id, repo.working_master(s).id


def _by_key(recs, prefix):
    return next(r for r in recs if approval.payload(r)["key"].startswith(prefix))


# --- review --------------------------------------------------------------------------------

def test_past_tense():
    assert [past_tense(w) for w in ("managing", "leading", "planning", "supplying", "creating", "x")] == [
        "managed", "led", "planned", "supplied", "created", None]


def test_review_scores_and_suggestions_never_add_facts():
    report = review(import_text(MESSY), ["Project Engineer"])
    assert 0 <= report.score <= 100 and len(report.categories) == 6
    assert "not a measure" in report.note
    proposed = {s.original: s.proposed for s in report.suggestions if s.action == "replace"}
    assert proposed["I was responsible for managing  the  budget for three projects"] == \
        "Managed the budget for three projects"
    assert proposed["Responsible for coordinating suppliers in order to reduce delays."] == \
        "Coordinated suppliers to reduce delays"
    assert proposed["Prepared managment reports"] == "Prepared management reports"
    assert proposed["Utilized SAP on a daily basis."] == "Used SAP daily"
    # "Helped with" could understate or overstate the role: advice and a question, never a rewrite.
    assert "Helped with testing new equipment" not in proposed
    assert any(q.target.startswith("item:") and "What exactly" in q.question for q in report.questions)
    assert {s.proposed for s in report.suggestions if s.action == "dates"} == {"Jan 2020 – Present",
                                                                               "Mar 2016 – Dec 2019"}
    assert sum(s.action == "remove" for s in report.suggestions) == 2  # repeated bullet and skill
    # No suggestion introduces a number that is not already in the line it changes.
    import re
    for s in report.suggestions:
        if s.action == "replace":
            assert set(re.findall(r"\d+", s.proposed)) <= set(re.findall(r"\d+", s.original))
    essential = {q.target for q in report.questions if q.essential}
    assert "contact.phone" in essential


def test_a_strong_cv_scores_well_and_relevance_is_optional():
    strong = review(import_text(QUALITY_CV))
    assert strong.score >= 85 and next(c for c in strong.categories if c.key == "relevance").score is None


# --- approval workflow ----------------------------------------------------------------------

def test_only_accepted_changes_reach_the_cv_and_can_be_undone(db):
    master_id, revised_id = _revised(db)
    with session_scope(db) as s:
        doc = repo.get_doc(s, revised_id)
        approval.store(s, doc, review(repo.load(doc)).suggestions)
        recs = approval.recommendations(s, doc)
        spelling = next(r for r in recs if "managment" in r.original)
        budget = next(r for r in recs if r.original.startswith("I was responsible"))
        approval.decide(s, doc, spelling.id, "accept")
        approval.decide(s, doc, budget.id, "reject")
        texts = [i.text for _, _, i in repo.load(doc).iter_items()]
        assert "Prepared management reports" in texts and budget.original in texts
        item = repo.load(doc).find_item(spelling.item_id)[2]
        assert item.provenance == "suggested"
        approval.decide(s, doc, spelling.id, "undo")
        assert "Prepared managment reports" in [i.text for _, _, i in repo.load(doc).iter_items()]
        assert spelling.status == "pending"
        approval.decide(s, doc, spelling.id, "edit", text="Prepared weekly management reports")
        edited = repo.load(doc).find_item(spelling.item_id)[2]
        assert edited.text == "Prepared weekly management reports" and edited.provenance == "edited"
        assert repo.load(repo.get_doc(s, master_id)).to_text() == import_text(MESSY).to_text()  # master untouched


def test_accept_all_skips_changes_that_need_confirmation(db):
    _, revised_id = _revised(db, MESSY.replace("SKILLS", "SKILLS").replace("Sam Sample\n", "Sam Sample\nEngineer\n"))
    with session_scope(db) as s:
        doc = repo.get_doc(s, revised_id)
        approval.store(s, doc, review(repo.load(doc)).suggestions)
        summary = _by_key(approval.recommendations(s, doc), "summary:add")
        assert summary.verification
        with pytest.raises(repo.WorkspaceError, match="Confirm"):
            approval.decide(s, doc, summary.id, "accept")
        result = approval.accept_all(s, doc)
        assert result.applied >= 5 and result.needs_confirmation >= 1
        assert summary.status == "pending"
        approval.decide(s, doc, summary.id, "accept", confirmed=True)
        assert repo.load(doc).section("summary") is not None
        assert approval.reject_all(s, doc) == 0  # nothing left except advice, which is noted not rejected
        assert any(r.status == "pending" and r.action == "advice" for r in approval.recommendations(s, doc))


def test_stale_suggestions_are_not_applied(db):
    _, revised_id = _revised(db)
    with session_scope(db) as s:
        doc = repo.get_doc(s, revised_id)
        approval.store(s, doc, review(repo.load(doc)).suggestions)
        rec = next(r for r in approval.recommendations(s, doc) if "managment" in r.original)
        content = repo.load(doc)
        content.set_item_text(rec.item_id, "Wrote reports", "edited")
        repo.save(s, doc, content)
        with pytest.raises(approval.StaleRecommendation):
            approval.decide(s, doc, rec.id, "accept")


def test_the_original_master_cannot_be_changed_by_the_workflow(db):
    master_id, _ = _revised(db)
    with session_scope(db) as s:
        master = repo.get_doc(s, master_id)
        approval.store(s, master, review(repo.load(master)).suggestions)
        rec = next(r for r in approval.recommendations(s, master) if r.action == "replace")
        with pytest.raises(repo.WorkspaceError, match="never changed"):
            approval.decide(s, master, rec.id, "accept")
        with pytest.raises(repo.WorkspaceError):
            approval.accept_all(s, master)


def test_restore_original_section(db):
    _, revised_id = _revised(db)
    with session_scope(db) as s:
        doc = repo.get_doc(s, revised_id)
        approval.store(s, doc, review(repo.load(doc)).suggestions)
        approval.accept_all(s, doc)
        exp = repo.load(doc).section("experience")
        approval.restore_section(s, doc, exp.id)
        restored = repo.load(doc).section("experience")
        assert restored.entries[0].items[0].text == "I was responsible for managing  the  budget for three projects"
        assert all(r.status == "pending" for r in approval.recommendations(s, doc) if r.section_id == exp.id
                   and r.action != "advice")


def test_decided_suggestions_are_not_asked_again(db):
    _, revised_id = _revised(db)
    with session_scope(db) as s:
        doc = repo.get_doc(s, revised_id)
        approval.store(s, doc, review(repo.load(doc)).suggestions)
        rec = next(r for r in approval.recommendations(s, doc) if r.original.startswith("Helped with"))
        approval.decide(s, doc, rec.id, "accept")  # advice: noted
        approval.store(s, doc, review(repo.load(doc)).suggestions)
        assert sum(r.original.startswith("Helped with") and r.action == "advice"
                   for r in approval.recommendations(s, doc)) == 1


# --- questions ---------------------------------------------------------------------------------

def test_answers_fill_gaps_only_with_what_the_user_wrote(db):
    _, revised_id = _revised(db)
    with session_scope(db) as s:
        doc = repo.get_doc(s, revised_id)
        approval.store_questions(s, doc, review(repo.load(doc)).questions)
        qs = {q.target: q for q in approval.questions(s, doc)}
        with pytest.raises(repo.WorkspaceError, match="Write an answer"):
            approval.answer(s, doc, qs["contact.phone"].id, "  ")
        with pytest.raises(repo.WorkspaceError, match="email"):
            approval._answer_into(repo.load(doc), "contact.email", "not-an-email")
        approval.answer(s, doc, qs["contact.phone"].id, "+44 20 0000 0000")
        approval.skip(s, doc, qs["contact.location"].id)
        approval.answer(s, doc, qs["section:education"].id, "BSc Civil Engineering — Example University — 2015")
        content = repo.load(doc)
        assert content.contact.phone == "+44 20 0000 0000" and content.contact.location == ""
        edu = content.section("education").entries[0]
        assert (edu.title, edu.organization, edu.provenance) == ("BSc Civil Engineering", "Example University", "edited")
        assert qs["contact.location"].status == "skipped"


def test_answers_in_a_tailored_cv_can_also_go_to_the_revised_master(db):
    master_id, revised_id = _revised(db)
    with session_scope(db) as s:
        version = repo.create_version(s, repo.get_doc(s, master_id), target_title="Engineer")
        approval.store_questions(s, version, review(repo.load(version)).questions)
        q = next(q for q in approval.questions(s, version) if q.target == "contact.phone")
        approval.answer(s, version, q.id, "+1 555 0100", also_revised_master=True)
        assert repo.load(repo.get_doc(s, revised_id)).contact.phone == "+1 555 0100"
        assert repo.load(repo.get_doc(s, master_id)).contact.phone == ""  # the original never changes
        assert q.added_to_master


# --- tailoring ---------------------------------------------------------------------------------

def test_tailoring_reorders_and_aligns_terms_but_never_claims_gaps():
    weights = get_settings().scoring_weights
    cv = import_text(QUALITY_CV.replace("Introduced SPC dashboards", "Introduced statistical process control "
                                                                      "dashboards").replace("SPC, ", ""))
    job = job_posting("Quality Engineer", QUALITY_JOB, "Example Devices")
    report = tailor(cv, job, weights)
    keys = {s.key.split(":")[0] for s in report.suggestions}
    assert {"summary", "order", "term", "addskill"} <= keys
    term = next(s for s in report.suggestions if s.key.startswith("term:"))
    assert "statistical process control (SPC)" in term.proposed
    add = [s for s in report.suggestions if s.key.startswith("addskill:")]
    assert add and all(s.verification and "genuinely" in s.verification for s in add)
    assert ("ISO 13485", "Required by the job; your CV does not mention it.") in report.gaps
    assert "ISO 13485" not in cv.to_text()


def test_tailored_changes_raise_the_match_score_only_through_approved_changes(db):
    weights = get_settings().scoring_weights
    master_id, _ = _revised(db, QUALITY_CV)
    job = job_posting("Quality Engineer", QUALITY_JOB, "Example Devices")
    with session_scope(db) as s:
        version = repo.create_version(s, repo.get_doc(s, master_id), target_title="Quality Engineer",
                                      target_company="Example Devices", job_description=QUALITY_JOB)
        before = score(repo.load(version), job, weights).score
        approval.store(s, version, tailor(repo.load(version), job, weights).suggestions, source="tailoring")
        assert score(repo.load(version), job, weights).score == before  # nothing applied yet
        iso = next(r for r in approval.recommendations(s, version) if r.proposed == "ISO 13485")
        approval.decide(s, version, iso.id, "accept", confirmed=True)
        assert score(repo.load(version), job, weights).score >= before
        assert "ISO 13485" not in repo.load(repo.get_doc(s, master_id)).to_text()


# --- PDF & DOCX ------------------------------------------------------------------------------

@pytest.mark.parametrize("template", ["original", "classic", "modern", "technical"])
def test_every_template_produces_valid_pdf_and_docx(template):
    content = import_text(QUALITY_CV)
    fmt = FormatSettings(template=template)
    pdf = render_pdf(content, fmt)
    v = validate_pdf(pdf.data, content)
    assert v.ok, v.problems
    with fitz.open(stream=pdf.data, filetype="pdf") as doc:
        assert doc.page_count == 1 and "Reduced scrap by 18%" in doc[0].get_text()
    docx = render_docx(content, fmt)
    assert validate_docx(docx, content).ok
    paragraphs = Document(io.BytesIO(docx)).paragraphs
    assert any(p.style.name == "List Bullet" for p in paragraphs) and paragraphs[0].text == "Alex Example"


def test_multi_page_cvs_keep_bullets_whole_and_are_numbered():
    roles = "".join(f"Engineer {n} — Company {n} — Jan 20{10 + n % 9} to Dec 20{11 + n % 9}\n" + "".join(
        f"- Delivered project number {n}.{k} with careful planning, testing and reporting across several teams "
        "and sites.\n" for k in range(5)) for n in range(14))
    content = import_text(QUALITY_CV.replace("EDUCATION", roles + "\nEDUCATION"))
    pdf = render_pdf(content, FormatSettings())
    v = validate_pdf(pdf.data, content)
    assert pdf.pages > 1 and v.ok, v.problems
    with fitz.open(stream=pdf.data, filetype="pdf") as doc:
        for number, page in enumerate(doc, start=1):
            text = page.get_text()
            assert f"page {number} of {doc.page_count}" in text
            if number > 1:
                assert not text.lstrip().startswith("and sites.")  # no bullet split across pages


def test_one_page_fitting_stays_readable():
    content = import_text(QUALITY_CV)
    result = render_pdf(content, FormatSettings(body_size=13, section_gap=18, line_height=1.6, margin=90),
                        one_page=True)
    assert result.fits_one_page and result.format.body_size >= 9


def test_validation_catches_missing_content():
    content = import_text(QUALITY_CV)
    other = import_text(QUALITY_CV.replace("- Reduced scrap by 18% through FMEA reviews with production teams.\n", ""))
    v = validate_pdf(render_pdf(other, FormatSettings()).data, content)
    assert not v.ok and "missing" in v.problems[0]
    assert not validate_pdf(b"not a pdf", content).ok and not validate_docx(b"nope", content).ok


def test_professional_filename():
    content = import_text(QUALITY_CV.replace("Alex Example", "Zoë Łukasz O'Brien"))
    assert professional_filename(content, "QA / Test Engineer", "pdf") == "Zoe_Lukasz_O_Brien_QA_Test_Engineer_CV.pdf"
    assert professional_filename(import_text("x"), None, "docx") == "CV.docx"


def test_exports_are_stored_encrypted_and_linked_to_the_revision_and_application(db):
    _, revised_id = _revised(db, QUALITY_CV)
    with session_scope(db) as s:
        doc = repo.get_doc(s, revised_id)
        app = add_manual(s, ApplicationInput("Quality Engineer", "Example Devices"))
        pdf = exports.generate(s, doc, "pdf", application=app)
        docx = exports.generate(s, doc, "docx")
        assert pdf.ok and docx.ok and pdf.filename == "Alex_Example_CV.pdf"
        assert pdf.file.revision_number == repo.latest_revision(s, doc).number and pdf.file.application_id == app.id
        raw = (get_settings().cv_storage_dir / pdf.file.blob).read_bytes()
        assert b"%PDF" not in raw and exports.file_bytes(pdf.file) == pdf.data
        assert [f.kind for f in exports.list_files(s, doc)] == ["docx", "pdf"] or \
            {f.kind for f in exports.list_files(s, doc)} == {"pdf", "docx"}
        assert exports.list_files(s, application=app) == [pdf.file]


def test_a_failed_export_is_never_offered(db, monkeypatch):
    _, revised_id = _revised(db, QUALITY_CV)
    from src.workspace import render
    monkeypatch.setattr(exports, "validate_pdf", lambda data, content: render.Validation(
        "pdf", False, 1, [("All content present", False, "1 line(s) missing")]))
    with session_scope(db) as s:
        result = exports.generate(s, repo.get_doc(s, revised_id), "pdf")
        assert not result.ok and result.data is None and result.file is None and "not offered" in result.error
        assert exports.list_files(s) == []


# --- Claude (optional) ---------------------------------------------------------------------------

def _ai_settings(monkeypatch, key="test-key"):
    settings = get_settings().model_copy(update={"cv_ai_enabled": True,
                                                 "anthropic_api_key": SecretStr(key) if key else None})
    return settings


class _FakeClient:
    def __init__(self, review, stop_reason="end_turn"):
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(parse=self._parse))
        self._review, self._stop = review, stop_reason

    def _parse(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(stop_reason=self._stop, parsed_output=self._review)


def test_claude_receives_no_contact_details_and_new_claims_are_flagged(monkeypatch):
    content = import_text(QUALITY_CV)
    first = content.section("experience").entries[0].items[0]
    review_out = ai.AIReview(overall_feedback="Solid.", changes=[
        ai.AIChange(item_id=first.id, kind="rewrite", category="experience", priority="High",
                    proposed="Led 8D root-cause analysis across three production lines.", explanation="Tighter.",
                    benefit="Clearer."),
        ai.AIChange(item_id=content.section("experience").entries[0].items[1].id, kind="rewrite",
                    category="experience", priority="High",
                    proposed="Introduced SPC dashboards in Tableau, cutting defects by 40%.", explanation="x",
                    benefit="y"),
        ai.AIChange(item_id="summary", kind="rewrite", category="summary", priority="Medium",
                    proposed="Quality engineer focused on supplier quality and SPC.", explanation="x", benefit="y"),
        ai.AIChange(item_id="unknown", kind="advice", category="structure", priority="Low", explanation="Add a link",
                    benefit="z"),
    ])
    client = _FakeClient(review_out)
    feedback, suggestions = ai.review_with_claude(content, _ai_settings(monkeypatch), client=client)
    sent = client.calls[0]["messages"][0]["content"]
    for private in ("Alex Example", "alex.example@example.com", "+00 000 000 000", "Example City"):
        assert private not in sent
    assert client.calls[0]["output_format"] is ai.AIReview and client.calls[0]["fallbacks"] == "default"
    clean, invented, summary, advice = suggestions
    assert clean.warnings is None and clean.source == "claude"
    assert "40" in invented.warnings and "Tableau" in invented.warnings
    assert summary.action == "replace" and summary.verification
    assert advice.action == "advice" and feedback == "Solid."


def test_claude_problems_fall_back_cleanly(monkeypatch):
    content = import_text(QUALITY_CV)
    with pytest.raises(ai.AIError, match="not set up"):
        ai.review_with_claude(content, _ai_settings(monkeypatch, key=None))
    with pytest.raises(ai.AIError, match="declined"):
        ai.review_with_claude(content, _ai_settings(monkeypatch), client=_FakeClient(None, "refusal"))
    with pytest.raises(ai.AIError, match="incomplete"):
        ai.tailor_with_claude(content, "QE", QUALITY_JOB, _ai_settings(monkeypatch),
                              client=_FakeClient(None, "max_tokens"))
    assert not ai.available(get_settings())  # tests never use a real key
