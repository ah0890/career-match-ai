from src.matching.engine import match_job
from src.ui.match_cards import breakdown_bars_html, match_card_html, match_summary_html
from tests.fixtures.match_factory import DEFAULT_WEIGHTS, job, profile


def test_summary_shows_score_confidence_and_skill_chips():
    html = match_summary_html(match_job(profile(), job(), DEFAULT_WEIGHTS))
    assert 'aria-label="Match score' in html and "/ 100 match" in html
    assert "confidence" in html
    assert "Found in your CV" in html and "Required, not found" in html and "ISO 13485" in html


def test_summary_flags_essential_requirements():
    r = match_job(profile(), job("Requirements\n- Kubernetes is essential\n"), DEFAULT_WEIGHTS)
    assert "1 essential requirement not found" in match_summary_html(r)


def test_match_card_keeps_attribution_and_original_link():
    html = match_card_html(match_job(profile(), job(), DEFAULT_WEIGHTS))
    assert "Source: " in html and 'href="https://himalayas.app/jobs/1"' in html
    assert html.index("cm-match") < html.index("cm-job-snippet")


def test_match_card_escapes_job_content():
    evil = job("Requirements\n- <script>alert(1)</script> Python\n", title="<img src=x onerror=alert(1)>",
               company="<b>Evil</b>")
    html = match_card_html(match_job(profile(), evil, DEFAULT_WEIGHTS))
    assert "<img" not in html and "<script>" not in html and "<b>Evil" not in html


def test_breakdown_lists_only_assessed_components_with_effective_weight():
    r = match_job(profile(), job("Requirements\n- Python and SQL for reporting\n"), DEFAULT_WEIGHTS)
    html = breakdown_bars_html(r)
    assert "Education" not in html  # not stated by the job, so not shown as a zero bar
    assert "Counts for" in html and "Required skills" in html


def test_low_confidence_score_is_shown_neutrally():
    from tests.fixtures.match_factory import SHORT_JOB

    html = match_summary_html(match_job(profile(), job(SHORT_JOB), DEFAULT_WEIGHTS))
    assert "cm-match-score cm-tone-neutral" in html and "limited information" in html
