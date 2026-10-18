from src.ui.components import empty_state_html, page_header_html
from src.ui.navigation import PAGES


def test_page_header_escapes_html():
    html = page_header_html("<script>x</script>", "a & b")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "a &amp; b" in html


def test_empty_state_is_announced_and_escaped():
    html = empty_state_html("No <b>jobs</b>", "Try again")
    assert 'role="status"' in html
    assert "<b>" not in html


def test_navigation_has_all_primary_pages_with_unique_paths():
    titles = [p.title for p in PAGES]
    assert titles == [
        "Dashboard", "Find Jobs", "CV Analysis", "Job Matches", "Company Intelligence",
        "Interview Preparation", "Application Tracker", "CV Versions", "Settings",
    ]
    assert len({p.url_path for p in PAGES}) == len(PAGES)
    assert all(p.icon.startswith(":material/") for p in PAGES)
