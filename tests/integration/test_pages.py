"""Render every page in a headless Streamlit runtime (offline)."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src.pages.find_jobs import validate_search
from src.ui.navigation import PAGES

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]


def _render(module: str) -> AppTest:
    script = (
        f"import sys\nsys.path.insert(0, {str(ROOT)!r})\n"
        "from src.ui.theme import apply_theme\n"
        f"import src.pages.{module} as page\n"
        "apply_theme()\npage.render()\n"
    )
    return AppTest.from_string(script, default_timeout=30).run()


def _html(at: AppTest) -> str:
    return " ".join(str(el.value) for el in at.get("html"))


@pytest.mark.parametrize("spec", PAGES, ids=lambda s: s.url_path)
def test_page_renders_without_exception(spec):
    at = _render(spec.module)
    assert not at.exception, at.exception
    assert spec.title.split()[0] in _html(at) or spec.module == "dashboard"


def test_dashboard_shows_honest_empty_activity():
    at = _render("dashboard")
    html = _html(at)
    assert "No activity yet" in html
    assert "Getting started" in html


def test_dashboard_quick_search_requires_keywords():
    at = _render("dashboard")
    at.button[0].click().run()
    assert any("Enter a job title" in e.value for e in at.error)


def test_find_jobs_validation_error_for_empty_query():
    at = _render("find_jobs")
    search = next(b for b in at.button if b.label == "Search")
    search.click().run()
    assert any("Enter a job title" in e.value for e in at.error)


def test_find_jobs_offline_reports_sources_not_searched_without_fabricating_results():
    at = _render("find_jobs")
    at.text_input(key="fj_query").input("Quality Engineer")
    next(b for b in at.button if b.label == "Search").click().run()
    assert not at.exception and not at.error
    html = _html(at)
    assert "0 jobs found" in html
    assert "Not searched" in html and "Offline mode is on" in html
    assert "<article" not in html  # no job cards rendered


def test_find_jobs_lists_unsupported_sources_honestly():
    at = _render("find_jobs")
    captions = " ".join(c.value for c in at.caption)
    assert "LinkedIn Jobs" in captions and "Indeed" in captions


def test_find_jobs_reset_clears_inputs():
    at = _render("find_jobs")
    at.text_input(key="fj_query").input("Engineer")
    next(b for b in at.button if b.label == "Search").click().run()
    next(b for b in at.button if b.label == "Reset").click().run()
    assert at.text_input(key="fj_query").value == ""
    assert "jobs found" not in _html(at)


def test_settings_shows_configured_weights():
    html = _html(_render("settings"))
    assert "Required skills" in html and "25%" in html
    assert "APPLY AFTER IMPROVEMENT" in html


@pytest.mark.parametrize("query,ok", [("", False), ("a", False), ("Data Analyst", True), ("x" * 201, False)])
def test_validate_search(query, ok):
    assert (validate_search(query) == []) is ok


def _render_with_cv(cv_bytes: bytes, name: str) -> AppTest:
    from src.cv.session import process_upload

    script = (
        f"import sys\nsys.path.insert(0, {str(ROOT)!r})\n"
        "from src.ui.theme import apply_theme\n"
        "import src.pages.cv_analysis as page\n"
        "apply_theme()\npage.render()\n"
    )
    at = AppTest.from_string(script, default_timeout=30)
    at.session_state["cm_active_cv"] = process_upload(name, cv_bytes, 5 * 1024 * 1024)
    return at.run()


def test_cv_analysis_shows_summary_for_active_cv():
    from tests.fixtures.cv_factory import make_text_pdf

    at = _render_with_cv(make_text_pdf(), "My CV.pdf")
    assert not at.exception
    html = _html(at)
    assert "My CV.pdf" in html and "Text extracted" in html and "Words extracted" in html
    assert any("PROFESSIONAL SUMMARY" in c.value for c in at.code)


def test_cv_analysis_scanned_pdf_explains_ocr():
    from tests.fixtures.cv_factory import make_image_only_pdf

    html = _html(_render_with_cv(make_image_only_pdf(), "scan.pdf"))
    assert "Needs OCR" in html and "Scanned document detected" in html


def test_cv_delete_requires_confirmation_then_removes_cv():
    from tests.fixtures.cv_factory import make_docx

    at = _render_with_cv(make_docx(), "cv.docx")
    at.button(key="cv_delete").click().run()
    assert "cm_active_cv" in at.session_state  # not deleted yet
    assert "cannot be undone" in _html(at)
    at.button(key="cv_delete_no").click().run()
    assert "cm_active_cv" in at.session_state
    at.button(key="cv_delete").click().run()
    at.button(key="cv_delete_yes").click().run()
    assert "cm_active_cv" not in at.session_state
    assert "Your CV" not in _html(at)


def test_dashboard_marks_upload_step_done_only_with_real_cv():
    from src.cv.session import process_upload
    from tests.fixtures.cv_factory import make_docx

    assert "Done" not in _html(_render("dashboard"))
    script = (
        f"import sys\nsys.path.insert(0, {str(ROOT)!r})\n"
        "import src.pages.dashboard as page\npage.render()\n"
    )
    at = AppTest.from_string(script, default_timeout=30)
    at.session_state["cm_active_cv"] = process_upload("cv.docx", make_docx(), 5 * 1024 * 1024)
    assert "Done" in _html(at.run())


def test_cv_analysis_renders_ats_report_and_tabs():
    from tests.fixtures.cv_factory import make_text_pdf

    at = _render_with_cv(make_text_pdf(), "cv.pdf")
    assert not at.exception
    assert [t.label for t in at.tabs] == ["ATS compatibility", "Structure and details", "Skills",
                                          "Compare with a job"]
    html = _html(at)
    assert "ATS compatibility" in html and "/ 100" in html
    assert "Prioritised improvements" in html
    assert "Name (estimated)" in html


def test_cv_job_compare_validates_and_shows_alignment():
    from tests.fixtures.cv_factory import make_text_pdf

    at = _render_with_cv(make_text_pdf(), "cv.pdf")
    at.text_area(key="cv_job_text").input("Too short")
    next(b for b in at.button if b.label == "Compare with my CV").click().run()
    assert any("longer job description" in e.value for e in at.error)

    jd = ("Quality Engineer with Six Sigma, FMEA, SPC and IATF 16949. " * 12).strip()
    at.text_input(key="cv_job_title").input("Quality Engineer")
    at.text_area(key="cv_job_text").input(jd)
    next(b for b in at.button if b.label == "Compare with my CV").click().run()
    assert not at.exception
    html = _html(at)
    assert "Job keyword alignment" in html and "IATF 16949" in html
    assert "Improve your CV for this job" in html and "IATF 16949: not found in your CV" in html


def test_scanned_cv_skips_analysis():
    from tests.fixtures.cv_factory import make_image_only_pdf

    at = _render_with_cv(make_image_only_pdf(), "scan.pdf")
    assert len(at.tabs) == 0


def _render_matches(cv=None, jobs=None) -> AppTest:
    from datetime import datetime, timezone

    from src.jobs.models import SearchQuery
    from src.providers.base import ProviderResult
    from src.services.job_search import SearchOutcome

    script = (
        f"import sys\nsys.path.insert(0, {str(ROOT)!r})\n"
        "from src.ui.theme import apply_theme\n"
        "import src.pages.job_matches as page\n"
        "apply_theme()\npage.render()\n"
    )
    at = AppTest.from_string(script, default_timeout=30)
    if cv is not None:
        at.session_state["cm_active_cv"] = cv
    if jobs is not None:
        at.session_state["fj_outcome"] = SearchOutcome(
            SearchQuery(keywords="Quality Engineer"),
            (ProviderResult("himalayas", "Himalayas", "ok", tuple(jobs)),),
            datetime.now(timezone.utc), unique_jobs=tuple(jobs))
    return at.run()


def _text_cv():
    from datetime import datetime, timezone

    from src.cv.session import ActiveCV
    from tests.fixtures.match_factory import QUALITY_CV, extraction

    return ActiveCV("Alex CV.pdf", 1000, "sha", datetime.now(timezone.utc), extraction(QUALITY_CV))


def test_job_matches_asks_for_cv_first():
    html = _html(_render_matches())
    assert "Upload your CV first" in html and "<article" not in html


def test_job_matches_asks_for_search_when_cv_present():
    html = _html(_render_matches(cv=_text_cv()))
    assert "No jobs to match yet" in html and "<article" not in html


def test_job_matches_ranks_jobs_with_breakdown():
    from tests.fixtures.match_factory import SHORT_JOB, job

    at = _render_matches(cv=_text_cv(), jobs=[job(SHORT_JOB, title="Quality Engineer"), job()])
    assert not at.exception
    html = _html(at)
    assert "2 jobs ranked for Alex CV.pdf" in html
    assert html.index("Senior Quality Engineer") < html.index(">Quality Engineer<")  # detailed job ranked first
    assert html.count("/ 100 match") == 1 and html.count("/ 100 · limited information") == 1
    assert len([e for e in at.expander if e.label.startswith("Why ")]) == 2
    assert len([e for e in at.expander if e.label == "Full job description"]) == 2
    assert len([e for e in at.expander if e.label == "Improve your CV for this job"]) == 2
    assert "Only add what is true" in html and "In experience" in html
    assert "Right to work" in html  # "check yourself" item from the detailed job
    assert any("too little information" in c.value for c in at.caption)
    assert "Apply after improvement" in html and "Don&#x27;t prioritize" in html
    assert "not a prediction of being shortlisted or hired" in " ".join(c.value for c in at.caption)
    assert "help you decide where to spend your effort" in " ".join(c.value for c in at.caption)


def test_job_matches_scanned_cv_explains_why_no_matching():
    from datetime import datetime, timezone

    from src.cv.extraction import ExtractionResult
    from src.cv.session import ActiveCV

    scanned = ActiveCV("scan.pdf", 10, "s", datetime.now(timezone.utc), ExtractionResult("", "pdf", 1, needs_ocr=True))
    assert "could not be read" in _html(_render_matches(cv=scanned))


def test_job_matches_filters_and_comparison():
    from tests.fixtures.match_factory import SHORT_JOB, job

    jobs = [job(), job(SHORT_JOB, title="Quality Engineer", source_job_id="short"),
            job("Requirements\n- SEO and HubSpot\n- 3+ years of experience in digital marketing\n" + "Marketing. " * 90,
                title="Marketing Manager", source_job_id="mkt")]
    at = _render_matches(cv=_text_cv(), jobs=jobs)
    at.slider(key="jm_min_score").set_value(80).run()
    html = _html(at)
    assert "Marketing Manager" not in html and "hidden by filters" in " ".join(c.value for c in at.caption)

    at.slider(key="jm_min_score").set_value(100).run()
    assert "No jobs match these filters" in _html(at)

    at.slider(key="jm_min_score").set_value(0).run()
    keys = at.multiselect(key="jm_compare").options
    assert len(keys) == 3
    at.multiselect(key="jm_compare").select(keys[0]).select(keys[1]).run()
    html = _html(at)
    assert "cm-compare" in html and "Essential requirements not found" in html


def test_job_matches_pages_long_result_lists():
    from tests.fixtures.match_factory import job

    jobs = [job(source_job_id=str(i), title=f"Quality Engineer {i}") for i in range(20)]
    at = _render_matches(cv=_text_cv(), jobs=jobs)
    assert _html(at).count("/ 100 match") == 15
    at.button(key="jm_next_bottom").click().run()
    assert _html(at).count("/ 100 match") == 5
    assert any("Showing 16–20 of 20" in c.value for c in at.caption)
