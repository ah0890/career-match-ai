"""Job-specific CV tailoring: suggested edits, preservation of the original and DOCX/PDF export."""

import io
import re

import pymupdf as fitz
from docx import Document

from src.matching.engine import match_job
from src.tailoring.document import (
    insert_section_after_preamble, parse_skill_list, render_skill_list, replace_section_body, section_body,
    split_roles,
)
from src.tailoring.edits import apply_edits, suggest_edits
from src.tailoring.export import to_docx, to_pdf
from tests.fixtures.match_factory import DEFAULT_WEIGHTS, QUALITY_CV, job, profile


def _edits(cv=QUALITY_CV, **kw):
    result = match_job(profile(cv), job(**kw), DEFAULT_WEIGHTS)
    return result, suggest_edits(cv, result)


def _by_kind(edits, kind):
    return [e for e in edits if e.kind == kind]


# The least relevant bullet of the first role moved to the top, so there is something to reorder.
_LEAD = "- Led root-cause analysis using 8D methods across three production lines."
_PPAP = "- Managed supplier PPAP submissions and incoming inspection plans."
SHUFFLED_CV = QUALITY_CV.replace(_LEAD, "@@").replace(_PPAP, _LEAD).replace("@@", _PPAP)


# --- document helpers -----------------------------------------------------

def test_replace_section_body_leaves_other_sections_untouched():
    out = replace_section_body(QUALITY_CV, "skills", "SQL, Python")
    assert section_body(out, "skills") == "SQL, Python"
    assert section_body(out, "experience") == section_body(QUALITY_CV, "experience")
    assert out.split("SKILLS")[0] == QUALITY_CV.split("SKILLS")[0]


def test_insert_section_goes_before_the_first_heading():
    cv = QUALITY_CV.replace("PROFESSIONAL SUMMARY\nQuality engineer with experience in manufacturing process "
                            "improvement and supplier quality management.\n\n", "")
    out = insert_section_after_preamble(cv, "PROFESSIONAL SUMMARY", "A summary.")
    assert out.index("PROFESSIONAL SUMMARY") < out.index("EXPERIENCE")
    assert out.startswith("Alex Example\n")


def test_skill_lists_round_trip_in_both_styles():
    inline = parse_skill_list("Python, SQL; Minitab")
    assert inline.items == ("Python", "SQL", "Minitab") and render_skill_list(inline) == "Python, SQL, Minitab"
    bullets = parse_skill_list("- Python\n- SQL")
    assert bullets.style == "bullets" and render_skill_list(bullets) == "- Python\n- SQL"


def test_roles_keep_their_own_bullets():
    roles = split_roles(section_body(QUALITY_CV, "experience"))
    assert len(roles) == 2
    assert len(roles[0][1]) == 3 and "FMEA" in roles[1][1][0]


# --- suggestions ----------------------------------------------------------

def test_skills_reorder_puts_job_skills_first_without_adding_or_removing():
    _, edits = _edits()
    [e] = _by_kind(edits, "skills_order")
    before, after = parse_skill_list(e.before).items, parse_skill_list(e.after).items
    assert sorted(before) == sorted(after) and before != after
    assert after.index("FMEA") < after.index("Python")


def test_bullet_reorder_never_moves_bullets_between_roles_or_rewords_them():
    _, edits = _edits(SHUFFLED_CV)
    [e] = _by_kind(edits, "bullet_order")
    before, after = split_roles(e.before), split_roles(e.after)
    assert [h for h, _ in before] == [h for h, _ in after]
    assert all(sorted(b1) == sorted(b2) for (_, b1), (_, b2) in zip(before, after))
    assert after[0][1][0] == _LEAD


def test_already_ordered_bullets_need_no_edit():
    _, edits = _edits()
    assert not _by_kind(edits, "bullet_order")


def test_summary_line_names_only_skills_the_cv_already_shows():
    result, edits = _edits()
    [e] = _by_kind(edits, "summary")
    added = e.after.replace(e.before, "")
    named = re.findall(r"[A-Za-z0-9 ]+", added.split(":", 1)[1])
    assert all(n.strip() in result.matched_skills for n in named for n in n.split(" and ") if n.strip())
    assert e.before.strip() in e.after


def test_missing_required_skills_need_confirmation_and_are_off_by_default():
    result, edits = _edits(description="Requirements\n- Kubernetes is essential\n- Python and SQL\n"
                                       + "We build fictional systems with a friendly team. " * 20)
    [e] = _by_kind(edits, "add_skill")
    assert e.after == "Kubernetes" and e.needs_confirmation and not e.default_on
    assert "Only add it if you genuinely have it" in e.why
    assert "Kubernetes" in result.missing_required_skills


def test_no_edits_for_an_irrelevant_job():
    _, edits = _edits(description="Pastry chef wanted for a fictional bakery. " * 20, title="Pastry Chef")
    assert not _by_kind(edits, "add_skill") and not _by_kind(edits, "skills_order")


# --- applying -------------------------------------------------------------

def test_rejecting_every_edit_returns_the_original_unchanged():
    _, edits = _edits()
    assert apply_edits(QUALITY_CV, edits, set()) == QUALITY_CV


def test_reorder_edits_preserve_every_original_line():
    _, edits = _edits()
    reorders = {e.id for e in edits if e.kind in ("skills_order", "bullet_order")}
    out = apply_edits(QUALITY_CV, edits, reorders)
    assert out != QUALITY_CV
    cv_lines = [ln for ln in QUALITY_CV.split("\n") if "," not in ln]  # skills line is reordered as a whole
    assert all(ln in out for ln in cv_lines)
    assert sorted(parse_skill_list(section_body(out, "skills")).items) == \
        sorted(parse_skill_list(section_body(QUALITY_CV, "skills")).items)


def test_all_accepted_edits_keep_dates_employers_and_education():
    _, edits = _edits()
    out = apply_edits(QUALITY_CV, edits, {e.id for e in edits if not e.needs_confirmation})
    for fact in ("Jan 2019 to Present", "Jun 2015 to Dec 2018", "Example Manufacturing Ltd",
                 "Sample Components Co", "BSc Mechanical Engineering — Example University — 2015",
                 "Reduced scrap by 18%", "alex.example@example.com"):
        assert fact in out
    assert "Key strengths for this role:" in out


def test_confirmed_skill_is_appended_once():
    _, edits = _edits(description="Requirements\n- Kubernetes is essential\n- Python and SQL\n"
                                  + "We build fictional systems with a friendly team. " * 20)
    [e] = _by_kind(edits, "add_skill")
    out = apply_edits(QUALITY_CV, edits + [e], {e.id})
    assert parse_skill_list(section_body(out, "skills")).items.count("Kubernetes") == 1


def test_summary_is_inserted_when_the_cv_has_none():
    cv = QUALITY_CV.replace("PROFESSIONAL SUMMARY\nQuality engineer with experience in manufacturing process "
                            "improvement and supplier quality management.\n\n", "")
    _, edits = _edits(cv)
    [e] = _by_kind(edits, "summary")
    assert e.before == "" and e.after.startswith("Professional with")
    out = apply_edits(cv, edits, {e.id})
    assert section_body(out, "summary") == e.after


# --- export ---------------------------------------------------------------

def test_docx_contains_the_real_cv_text_with_headings_and_bullets():
    doc = Document(io.BytesIO(to_docx(QUALITY_CV)))
    paras = [(p.style.name, p.text) for p in doc.paragraphs]
    assert paras[0] == ("Title", "Alex Example")
    assert ("Heading 1", "Experience") in paras
    assert ("List Bullet", "Reduced scrap by 18% through FMEA reviews with production teams.") in paras
    text = "\n".join(t for _, t in paras)
    assert "Six Sigma, ISO 9001, FMEA, SPC, Python, SQL, Minitab" in text


def test_pdf_has_selectable_text_for_every_line():
    pdf = fitz.open(stream=to_pdf(QUALITY_CV), filetype="pdf")
    text = " ".join(" ".join(page.get_text().split()) for page in pdf)
    for line in ("Alex Example", "Senior Quality Engineer", "Reduced scrap by 18%", "Example University"):
        assert line in text
    assert pdf.page_count >= 1


def test_pdf_escapes_markup_in_cv_text():
    pdf = fitz.open(stream=to_pdf("Alex <b>Example</b>\nSKILLS\nC++ & <script>"), filetype="pdf")
    text = "".join(page.get_text() for page in pdf)
    assert "<b>Example</b>" in text and "<script>" in text


def test_long_cvs_flow_onto_more_pages():
    long_cv = QUALITY_CV + "\n".join(f"- Fictional achievement number {i}." for i in range(150))
    assert fitz.open(stream=to_pdf(long_cv), filetype="pdf").page_count > 1
