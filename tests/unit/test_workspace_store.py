"""CV workspace: import, encrypted originals, master CV, independent versions, revisions and job links."""

import pytest
from sqlalchemy import select

from config.settings import get_settings
from src.cv.extraction import CVValidationError
from src.db.engine import session_scope
from src.db.models import CVRevision
from src.tracker.repository import ApplicationInput, add_manual, get, set_status
from src.workspace import files
from src.workspace import repository as repo
from src.workspace.importer import import_text, style_from_docx, style_from_pdf
from src.workspace.style import MIN_BODY_SIZE, MIN_MARGIN, FormatSettings, StyleProfile
from tests.fixtures.cv_factory import make_docx, make_image_only_pdf, make_text_pdf
from tests.fixtures.match_factory import QUALITY_CV


@pytest.fixture
def db():
    return get_settings().database_url


def _master(db):
    with session_scope(db) as s:
        source = repo.import_source(s, "cv.pdf", make_text_pdf(), max_bytes=5_000_000)
        return repo.create_master(s, source).id, source.id


# --- import ---------------------------------------------------------------------------------

def test_import_structures_contact_roles_bullets_and_skills():
    doc = import_text(QUALITY_CV)
    assert doc.contact.name == "Alex Example" and doc.contact.email == "alex.example@example.com"
    exp = doc.section("experience")
    assert [(e.title, e.organization, e.dates) for e in exp.entries] == [
        ("Senior Quality Engineer", "Example Manufacturing Ltd", "Jan 2019 to Present"),
        ("Quality Engineer", "Sample Components Co", "Jun 2015 to Dec 2018")]
    assert len(exp.entries[0].items) == 3 and exp.entries[1].items[0].text.startswith("Reduced scrap by 18%")
    assert [i.text for i in doc.section("skills").entries[0].items][:3] == ["Six Sigma", "ISO 9001", "FMEA"]
    assert all(i.provenance == "extracted" for _, _, i in doc.iter_items())


def test_round_trip_text_keeps_every_fact():
    text = import_text(QUALITY_CV).to_text()
    for fact in ("Jan 2019 to Present", "Reduced scrap by 18%", "BSc Mechanical Engineering", "Minitab",
                 "alex.example@example.com"):
        assert fact in text
    assert import_text(text).to_text() == text  # stable


def test_unknown_headings_become_custom_sections():
    doc = import_text("Alex Example\nalex@example.com\n\nEXPERIENCE\nAnalyst — Example Ltd — 2020 - 2023\n- Did X\n\n"
                      "SECURITY CLEARANCE\nActive clearance level two\n")
    assert [s.kind for s in doc.sections] == ["experience", "custom"]
    assert doc.sections[1].title == "Security Clearance"


def test_style_is_read_from_the_original():
    pdf = style_from_pdf(make_text_pdf())
    assert pdf.source == "original" and pdf.body_size > 0 and pdf.margin_left == pdf.margin_right
    docx = style_from_docx(make_docx())
    assert docx.page_width == 612 and docx.margin_left == 90
    settings = FormatSettings.from_profile(StyleProfile.default().model_copy(update={"body_size": 6, "margin_left": 5,
                                                                                    "margin_right": 5}))
    assert settings.body_size == MIN_BODY_SIZE and settings.margin == MIN_MARGIN  # readable limits


# --- originals --------------------------------------------------------------------------------

def test_originals_are_stored_encrypted_and_unchanged(db):
    data = make_text_pdf()
    with session_scope(db) as s:
        source = repo.import_source(s, "My CV.pdf", data, max_bytes=5_000_000)
        raw = (get_settings().cv_storage_dir / source.blob).read_bytes()
        assert b"%PDF" not in raw and data not in raw  # encrypted at rest
        assert repo.source_bytes(source) == data
        assert source.extracted_text and not source.needs_ocr


def test_invalid_and_scanned_uploads(db):
    with session_scope(db) as s, pytest.raises(CVValidationError):
        repo.import_source(s, "cv.txt", b"hello", max_bytes=5_000_000)
    with session_scope(db) as s:
        scanned = repo.import_source(s, "scan.pdf", make_image_only_pdf(), max_bytes=5_000_000)
        assert scanned.needs_ocr
        ocr = repo.import_source(s, "scan.pdf", make_image_only_pdf(), max_bytes=5_000_000, ocr_text=QUALITY_CV)
        assert not ocr.needs_ocr and "Alex Example" in ocr.extracted_text


def test_stored_file_names_cannot_escape_the_folder():
    with pytest.raises(ValueError):
        files.get("../secrets.bin")


# --- master & versions ------------------------------------------------------------------------

def test_versions_are_independent_of_the_master_and_each_other(db):
    master_id, _ = _master(db)
    with session_scope(db) as s:
        master = repo.get_doc(s, master_id)
        a = repo.create_version(s, master, target_title="Quality Engineer", target_company="Company A")
        b = repo.create_version(s, master, target_title="QA Specialist", target_company="Company B")
        assert (a.name, b.name) == ("Quality Engineer — Company A", "QA Specialist — Company B")
        content = repo.load(a)
        item = next(i for _, _, i in content.iter_items())
        content.set_item_text(item.id, "Changed only in A", "edited")
        repo.save(s, a, content, revision=("edit", "Edited"))
        a_id, b_id = a.id, b.id
    with session_scope(db) as s:
        texts = {d: [i.text for _, _, i in repo.load(repo.get_doc(s, d)).iter_items()]
                 for d in (master_id, a_id, b_id)}
        assert "Changed only in A" in texts[a_id]
        assert "Changed only in A" not in texts[master_id] and "Changed only in A" not in texts[b_id]


def test_revisions_are_immutable_and_restore_creates_a_new_one(db):
    master_id, _ = _master(db)
    with session_scope(db) as s:
        master = repo.get_doc(s, master_id)
        original = master.content_json
        content = repo.load(master)
        content.contact.headline = "Quality Engineer"
        repo.save(s, master, content, revision=("edit", "Added headline"))
        restored = repo.restore(s, master, 1)
        numbers = [r.number for r in s.scalars(select(CVRevision).where(CVRevision.doc_id == master_id))]
        assert restored.number == numbers[-1] and len(numbers) == 3
        assert master.content_json == original
        assert repo.load(repo.get_revision(s, master, 2)).contact.headline == "Quality Engineer"  # history kept


def test_unchanged_saves_do_not_create_revisions(db):
    master_id, _ = _master(db)
    with session_scope(db) as s:
        master = repo.get_doc(s, master_id)
        assert repo.snapshot(s, master, "edit", "again").number == 1


def test_replacing_the_master_keeps_the_previous_content(db):
    master_id, _ = _master(db)
    with session_scope(db) as s:
        docx = repo.import_source(s, "new.docx", make_docx(), max_bytes=5_000_000)
        master = repo.create_master(s, docx)
        assert master.id == master_id and len(master.revisions) >= 2


def test_compare_highlights_added_removed_and_changed(db):
    a = import_text(QUALITY_CV)
    b = a.model_copy(deep=True)
    _, _, first = next(b.iter_items())
    first.text = "A clearer summary."
    exp = b.section("experience")
    removed = exp.entries[0].items.pop()
    from src.workspace.document import Item
    exp.entries[1].items.append(Item(text="Trained six inspectors.", provenance="edited"))
    kinds = {(c.kind, c.after or c.before) for c in repo.compare(a, b)}
    assert ("changed", "A clearer summary.") in kinds and ("removed", removed.text) in kinds
    assert ("added", "Trained six inspectors.") in kinds
    assert "+- Trained six inspectors." in repo.text_diff(a, b)


def test_rename_duplicate_archive_delete(db):
    master_id, _ = _master(db)
    with session_scope(db) as s:
        master = repo.get_doc(s, master_id)
        v = repo.create_version(s, master, target_title="Analyst")
        repo.rename(s, v, "Analyst — Example Ltd")
        copy = repo.duplicate(s, v)
        assert copy.name == "Analyst — Example Ltd (copy)" and copy.parent_id == v.id
        repo.set_archived(s, copy, True)
        assert copy not in repo.list_docs(s)
        with pytest.raises(repo.WorkspaceError):
            repo.delete(s, master)
        repo.delete(s, copy)
        assert repo.get_master(s) is not None  # never affected


# --- job applications ---------------------------------------------------------------------------

def test_submitted_applications_keep_the_exact_cv_revision(db):
    master_id, _ = _master(db)
    with session_scope(db) as s:
        version = repo.create_version(s, repo.get_doc(s, master_id), target_title="Analyst", job_key="himalayas:1")
        app = add_manual(s, ApplicationInput("Analyst", "Example Ltd", status="To Apply"))
        repo.select_for_application(s, app, version)
        assert app.cv_revision_number is None  # not sent yet
        set_status(s, app.id, "Application Submitted")
        pinned = app.cv_revision_number
        assert pinned == 1
        content = repo.load(version)
        content.contact.headline = "Changed after sending"
        repo.save(s, version, content, revision=("edit", "Later edit"))
        doc, rev = repo.application_cv(s, get(s, app.id))
        assert rev.number == 1 and repo.load(rev).contact.headline != "Changed after sending"
        with pytest.raises(repo.WorkspaceError, match="Archive it instead"):
            repo.delete(s, version)
        assert repo.suggest_for_job(s, "himalayas:1", None, None).id == version.id
        assert repo.suggest_for_job(s, "other", "x", "y").role == "master"
