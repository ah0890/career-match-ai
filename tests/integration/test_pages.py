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


def test_find_jobs_reports_no_sources_without_fabricating_results():
    at = _render("find_jobs")
    at.text_input(key="fj_query").input("Quality Engineer")
    next(b for b in at.button if b.label == "Search").click().run()
    assert not at.exception
    assert not at.error
    assert "No job sources configured" in _html(at)


def test_find_jobs_reset_clears_inputs():
    at = _render("find_jobs")
    at.text_input(key="fj_query").input("Engineer")
    next(b for b in at.button if b.label == "Search").click().run()
    next(b for b in at.button if b.label == "Reset").click().run()
    assert at.text_input(key="fj_query").value == ""
    assert "No job sources configured" not in _html(at)


def test_settings_shows_configured_weights():
    html = _html(_render("settings"))
    assert "Required skills" in html and "25%" in html
    assert "APPLY AFTER IMPROVEMENT" in html


@pytest.mark.parametrize("query,ok", [("", False), ("a", False), ("Data Analyst", True), ("x" * 201, False)])
def test_validate_search(query, ok):
    assert (validate_search(query) == []) is ok
