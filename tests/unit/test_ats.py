from datetime import date

import pytest

from src.cv.ats import analyse_cv, job_alignment, job_keywords, score_band
from src.cv.extraction import ExtractionResult, normalize_text
from src.cv.parsing import parse_cv
from tests.fixtures.cv_factory import SAMPLE_CV_TEXT

TODAY = date(2026, 10, 1)


def _report(text: str, **ex_kwargs):
    text = normalize_text(text)
    ex = ExtractionResult(text, ex_kwargs.pop("kind", "pdf"), ex_kwargs.pop("page_count", 1), **ex_kwargs)
    return analyse_cv(ex, parse_cv(text, today=TODAY))


GOOD_CV = SAMPLE_CV_TEXT + "\n" + "\n".join(
    f"• Improved process {i} yield by {i + 5}% through structured problem solving" for i in range(20)
)


def test_score_is_sum_of_components_and_within_range():
    report = _report(GOOD_CV)
    assert 0 <= report.score <= 100
    assert report.score == round(sum(c.score for c in report.components))
    assert sum(c.max_score for c in report.components) == 100


def test_good_cv_scores_well_and_breakdown_is_explained():
    report = _report(GOOD_CV)
    assert report.score >= 80, [(c.label, c.score) for c in report.components]
    assert all(check.detail for comp in report.components for check in comp.checks)
    assert "no score can predict" in report.limitations  # never claims to be a real ATS result


def test_scanned_cv_scores_zero_readability_and_high_priority_advice():
    report = _report("", needs_ocr=True, scanned_pages=(1,))
    readability = next(c for c in report.components if c.key == "readability")
    assert readability.score == 0
    assert report.recommendations[0].priority == "High"
    assert report.score < 50


def test_missing_sections_lower_score_and_produce_recommendations():
    full = _report(GOOD_CV)
    stripped = _report(GOOD_CV.replace("EDUCATION", "Studies").replace("SKILLS", "Stuff I know"))
    assert stripped.score < full.score
    titles = {r.title for r in stripped.recommendations}
    assert "Education section" in titles and "Skills section" in titles


def test_missing_contact_details_flagged():
    report = _report(GOOD_CV.replace("alex.example@example.com", "").replace("+00 000 000 000", ""))
    titles = {r.title for r in report.recommendations}
    assert {"Email address", "Phone number"} <= titles


def test_recommendations_sorted_by_priority():
    order = {"High": 0, "Medium": 1, "Low": 2}
    recs = _report("Short text with no structure at all").recommendations
    assert [order[r.priority] for r in recs] == sorted(order[r.priority] for r in recs)


def test_no_bullets_is_reported_not_crashed():
    report = _report("EXPERIENCE\nEngineer at Example 2019 - 2021")
    content = next(c for c in report.components if c.key == "content")
    assert content.score == 0
    assert any("no bullet" in ch.detail.lower() for ch in content.checks)


def test_long_pdf_penalised():
    report = _report(GOOD_CV, page_count=5)
    fmt = next(c for c in report.components if c.key == "format")
    assert next(ch for ch in fmt.checks if ch.label == "Page count").points == 0


@pytest.mark.parametrize("score,band", [(90, "Strong"), (85, "Strong"), (75, "Good"), (55, "Needs improvement"),
                                        (10, "Significant issues")])
def test_score_bands(score, band):
    assert score_band(score) == band


JOB = (
    "We are hiring a Senior Quality Engineer to lead supplier quality and root cause analysis. "
    "Requirements: Six Sigma, FMEA, SPC, ISO 9001 and IATF 16949. Experience with Minitab and Python is "
    "preferred. The quality engineer will drive corrective actions, supplier audits and audits of "
    "production processes, and coordinate corrective actions with suppliers across automotive programs. "
    "Automotive experience is essential; supplier development and audits are a core part of the role. "
    "You will report to the plant quality manager and work closely with engineering and purchasing."
)


def test_job_alignment_matches_and_missing_skills():
    a = job_alignment(normalize_text(SAMPLE_CV_TEXT), JOB)
    assert {"Six Sigma", "FMEA", "Statistical Process Control", "ISO 9001", "Minitab", "Python"} <= set(a.matched_skills)
    assert "IATF 16949" in a.missing_skills
    assert 0 <= a.score <= 100
    assert a.reliable
    assert "not that you lack it" in a.note


def test_job_alignment_short_description_unreliable():
    a = job_alignment(SAMPLE_CV_TEXT, "Engineer needed. Python.")
    assert not a.reliable
    assert "unreliable" in a.note


def test_job_keywords_skip_stopwords_and_need_repetition():
    kws = job_keywords(JOB)
    assert "supplier" in kws or "suppliers" in kws
    assert "the" not in kws and "experience" not in kws
    assert "programs" not in kws  # appears once
