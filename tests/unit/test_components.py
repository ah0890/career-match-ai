import importlib

import pytest

from src.ui.components import (
    Feature, Metric, Step, badge_html, empty_state_html, feature_grid_html, key_value_html,
    metric_grid_html, notice_html, page_header_html, section_header_html, steps_html,
)
from src.ui.navigation import PAGES, get_spec

XSS = "<script>alert(1)</script>"


def test_page_header_escapes_html():
    html = page_header_html("<script>x</script>", "a & b", eyebrow="<i>e</i>")
    assert "<script>" not in html and "<i>" not in html
    assert "&lt;script&gt;" in html
    assert "a &amp; b" in html


def test_empty_state_is_announced_and_escaped():
    html = empty_state_html("No <b>jobs</b>", "Try again")
    assert 'role="status"' in html
    assert "<b>" not in html


@pytest.mark.parametrize("builder", [
    lambda: section_header_html(XSS, XSS),
    lambda: badge_html(XSS),
    lambda: notice_html(XSS, title=XSS),
    lambda: metric_grid_html([Metric(XSS, XSS, XSS)]),
    lambda: feature_grid_html([Feature(XSS, XSS)]),
    lambda: steps_html([Step(XSS, XSS)]),
    lambda: key_value_html([(XSS, XSS)]),
])
def test_all_builders_escape_dynamic_text(builder):
    html = builder()
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_badge_carries_text_not_only_colour():
    html = badge_html("Offer", "success")
    assert ">Offer<" in html and "cm-tone-success" in html


def test_unknown_tone_rejected():
    with pytest.raises(ValueError):
        badge_html("x", "purple")  # type: ignore[arg-type]


def test_danger_notice_uses_alert_role():
    assert 'role="alert"' in notice_html("Failed", "danger")
    assert 'role="status"' in notice_html("FYI", "info")


def test_steps_label_state_in_text():
    html = steps_html([Step("A", "a", done=True), Step("B", "b")])
    assert "Done" in html and "To do" in html
    assert html.startswith("<ol")


def test_navigation_has_all_primary_pages_with_unique_paths():
    titles = [p.title for p in PAGES]
    assert titles == [
        "Dashboard", "Find Jobs", "CV Analysis", "Job Matches", "Tailor CV", "Company Intelligence",
        "Interview Preparation", "Application Tracker", "Email Tracking", "CV Versions", "Settings",
    ]
    assert len({p.url_path for p in PAGES}) == len(PAGES)
    assert all(p.icon.startswith(":material/") for p in PAGES)


@pytest.mark.parametrize("spec", PAGES, ids=lambda s: s.url_path)
def test_every_page_module_exposes_render(spec):
    module = importlib.import_module(f"src.pages.{spec.module}")
    assert callable(module.render)


def test_get_spec_rejects_unknown_page():
    with pytest.raises(KeyError):
        get_spec("nowhere")
