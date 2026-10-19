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


def test_company_intelligence_offline_reports_error_without_inventing_facts():
    at = _render("company_intelligence")
    at.text_input(key="ci_name").input("Example Devices")
    next(b for b in at.button if b.label == "Find company").click().run()
    assert any("Offline mode" in e.value for e in at.error)
    assert "Key facts" not in _html(at)


def test_company_intelligence_lists_companies_from_results_and_renders_profile():
    from datetime import datetime, timezone

    from src.company.models import CompanyProfile, Fact, Source, Summary
    from src.jobs.models import SearchQuery
    from src.providers.base import ProviderResult
    from src.services.job_search import SearchOutcome
    from tests.fixtures.match_factory import job

    jobs = [job(company="Example Devices Ltd")]
    src = Source("Wikidata", "https://www.wikidata.org/wiki/Q901", "CC0 1.0")
    profile = CompanyProfile("Q901", "Example Devices", "fictional manufacturer",
                             Summary("A fictional company.", Source("Wikipedia", "https://en.wikipedia.org/wiki/X", "CC BY-SA 4.0")),
                             (Fact("Industry", "medical technology", src),), (), "https://devices.example.com",
                             ("Products",), datetime.now(timezone.utc), ("Check important facts.",))
    script = (f"import sys\nsys.path.insert(0, {str(ROOT)!r})\n"
              "from src.ui.theme import apply_theme\nimport src.pages.company_intelligence as page\n"
              "apply_theme()\npage.render()\n")
    at = AppTest.from_string(script, default_timeout=30)
    at.session_state["fj_outcome"] = SearchOutcome(SearchQuery(keywords="Quality"),
                                                   (ProviderResult("himalayas", "Himalayas", "ok", tuple(jobs)),),
                                                   datetime.now(timezone.utc), unique_jobs=tuple(jobs))
    at.run()
    assert "Example Devices Ltd" in at.selectbox(key="ci_pick").options
    at.session_state["ci_profile"] = profile
    at.run()
    assert not at.exception
    html = _html(at)
    assert "medical technology" in html and 'href="https://www.wikidata.org/wiki/Q901"' in html
    assert "CC BY-SA 4.0" in html and "Official website" in html
    assert any("Not available from these sources: Products" in c.value for c in at.caption)
    assert "Relevance to your search" in html and "Senior Quality Engineer" in html


def _render_page_with(module, cv=None, jobs=None, state=None) -> AppTest:
    from datetime import datetime, timezone

    from src.jobs.models import SearchQuery
    from src.providers.base import ProviderResult
    from src.services.job_search import SearchOutcome

    script = (f"import sys\nsys.path.insert(0, {str(ROOT)!r})\n"
              f"from src.ui.theme import apply_theme\nimport src.pages.{module} as page\napply_theme()\npage.render()\n")
    at = AppTest.from_string(script, default_timeout=30)
    if cv is not None:
        at.session_state["cm_active_cv"] = cv
    if jobs is not None:
        at.session_state["fj_outcome"] = SearchOutcome(
            SearchQuery(keywords="Quality Engineer"), (ProviderResult("himalayas", "Himalayas", "ok", tuple(jobs)),),
            datetime.now(timezone.utc), unique_jobs=tuple(jobs))
    for k, v in (state or {}).items():
        at.session_state[k] = v
    return at.run()


def test_interview_preparation_empty_states():
    assert "Upload your CV first" in _html(_render_page_with("interview_preparation"))
    assert "No jobs to prepare for yet" in _html(_render_page_with("interview_preparation", cv=_text_cv()))


def test_interview_preparation_builds_plan_for_prefilled_job():
    from tests.fixtures.match_factory import SHORT_JOB, job

    jobs = [job(), job(SHORT_JOB, title="Quality Engineer", source_job_id="short")]
    at = _render_page_with("interview_preparation", cv=_text_cv(), jobs=jobs, state={"ip_prefill": jobs[1].key})
    assert not at.exception
    assert at.selectbox(key="ip_job").value == jobs[1].key
    at.selectbox(key="ip_job").set_value(jobs[0].key).run()
    html = _html(at)
    assert "Tell me about yourself." in html and "Why it may come up" in html and "From your CV" in html
    assert "Questions to ask the interviewer" in html
    assert len(at.get("download_button")) == 1
    assert any("predictions based on the job description" in str(el.value) for el in at.get("html"))


def test_interview_study_plan_tracks_progress():
    from tests.fixtures.match_factory import job

    desc = "Requirements\n- Kubernetes is essential\n- Minitab and SQL\n" + "Quality work. " * 60
    jobs = [job(desc)]
    at = _render_page_with("interview_preparation", cv=_text_cv(), jobs=jobs)
    assert not at.exception
    assert [t.label for t in at.tabs] == ["Questions", "Study plan"]
    html = _html(at)
    assert "Learn the essentials of Kubernetes" in html and "Official documentation" in html
    key = f"ip_status_{jobs[0].key}_learn:Kubernetes"
    at.segmented_control(key=key).set_value("Prepared").run()
    from config.settings import get_settings
    from src.db.engine import session_scope
    from src.tracker.repository import study_statuses

    with session_scope(get_settings().database_url) as s:
        assert study_statuses(s, jobs[0].key)["learn:Kubernetes"] == "Prepared"
    bar = at.get("progress")[0]
    assert bar.proto.text == "1 of 4 topics prepared" and bar.value == 25


def test_tracker_add_change_status_and_delete():
    at = _render("application_tracker")
    assert "No applications tracked yet" in _html(at)
    form_inputs = at.text_input
    form_inputs[0].input("Quality Engineer")
    form_inputs[1].input("Example Devices")
    next(b for b in at.button if b.label == "Add to tracker").click().run()
    assert not at.exception
    html = _html(at)
    assert "Quality Engineer" in html and "1 application" in html
    app_key = next(k for k in at.session_state if str(k).startswith("at_status_"))
    at.selectbox(key=app_key).set_value("Applied").run()
    html = _html(at)
    assert "Applied" in html
    at.button(key=app_key.replace("at_status_", "at_delete_")).click().run()
    at.button(key=app_key.replace("at_status_", "at_delete_yes_")).click().run()
    assert "No applications tracked yet" in _html(at)


def test_job_matches_save_to_tracker():
    from tests.fixtures.match_factory import job

    jobs = [job()]
    at = _render_page_with("job_matches", cv=_text_cv(), jobs=jobs)
    at.button(key="jm_save_0").click().run()
    assert not at.exception
    assert at.button(key="jm_saved_0").disabled


def test_find_jobs_records_history_and_searches_again():
    at = _render("find_jobs")
    at.text_input(key="fj_query").input("Quality Engineer")
    at.selectbox(key="fj_arrangement").set_value("Remote")
    next(b for b in at.button if b.label == "Search").click().run()
    next(b for b in at.button if b.label == "Reset").click().run()
    assert at.text_input(key="fj_query").value == ""
    assert any(e.label == "Recent searches" for e in at.expander)
    again = next(b for b in at.button if b.label == "Search again")
    again.click().run()
    assert not at.exception
    assert at.text_input(key="fj_query").value == "Quality Engineer"
    assert at.selectbox(key="fj_arrangement").value == "Remote"
    assert "jobs found" in _html(at)


def test_settings_shows_stored_job_data_controls():
    html = _html(_render("settings"))
    assert "Stored job data" in html and "Cached source responses" in html


def test_dashboard_shows_metrics_charts_and_top_matches_from_real_data():
    from config.settings import get_settings
    from src.db.engine import session_scope
    from src.tracker.repository import ApplicationInput, add_manual, set_status
    from tests.fixtures.match_factory import job

    with session_scope(get_settings().database_url) as s:
        app_id = add_manual(s, ApplicationInput("Quality Engineer", "Example Devices")).id
    with session_scope(get_settings().database_url) as s:
        set_status(s, app_id, "Applied")
    jobs = [job(), job(source_job_id="2", title="Quality Lead"), job(source_job_id="3", title="Quality Manager")]
    at = _render_page_with("dashboard", cv=_text_cv(), jobs=jobs)
    assert not at.exception
    html = _html(at)
    assert "No activity yet" not in html
    assert "Strong matches" in html and "Active applications" in html
    assert "Top matches in your latest results" in html
    assert len(at.get("plotly_chart")) == 3  # pipeline, weekly applications, score distribution
    assert sum(1 for e in at.expander if e.label == "View as table") == 3
    assert "Done" in html


def test_cv_versions_requires_consent_then_saves_and_loads():
    at = _render_page_with("cv_versions", cv=_text_cv())
    assert "No CV versions yet" in _html(at)
    name_input = next(t for t in at.text_input if t.label == "Version name")
    name_input.input("Quality roles")
    next(b for b in at.button if b.label == "Save version").click().run()
    assert any("Tick the box" in e.value for e in at.error)

    next(t for t in at.text_input if t.label == "Version name").input("Quality roles")
    next(c for c in at.checkbox if "keep this CV" in c.label).check()
    next(b for b in at.button if b.label == "Save version").click().run()
    assert not at.exception
    html = _html(at)
    assert "1 saved version" in html and "Active CV" in html
    assert "Your active CV is saved as “Quality roles”." in html


def test_settings_reports_saved_versions():
    html = _html(_render("settings"))
    assert "Saved CV versions" in html and "unless you save a version" in html
