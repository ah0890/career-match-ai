"""The explainable matching engine and its session cache."""

from datetime import datetime, timezone

import pytest

from config.settings import ScoringWeights
from src.cv.session import ActiveCV
from src.matching.engine import match_job, rank_jobs
from src.providers.base import ProviderResult
from src.services.job_search import SearchOutcome
from src.services.matching import clear_matches, ranked_matches
from tests.fixtures.match_factory import DEFAULT_WEIGHTS, QUALITY_CV, SHORT_JOB, extraction, job, profile


def _component(result, key):
    return next(c for c in result.components if c.key == key)


def test_strong_match_scores_high_with_evidence():
    r = match_job(profile(), job(), DEFAULT_WEIGHTS)
    assert r.score >= 80
    assert r.confidence in ("High", "Medium")
    assert {"FMEA", "Minitab", "SQL"} <= set(r.matched_skills)
    assert r.missing_required_skills == ("ISO 13485",)
    assert r.missing_preferred_skills == ("Tableau",)
    skills = _component(r, "required_skills")
    assert any("required skill(s) found in your CV" in e for e in skills.evidence)
    assert any("Tableau (preferred) — not found in your CV." == g for g in skills.gaps)


def test_every_component_explains_itself():
    r = match_job(profile(), job(), DEFAULT_WEIGHTS)
    for c in r.components:
        assert c.assessed and (c.evidence or c.note)
        assert 0 <= c.score <= 1


def test_experience_uses_dated_years_and_title_relevance():
    exp = _component(match_job(profile(), job(), DEFAULT_WEIGHTS), "experience")
    assert exp.score == 1.0
    assert any("asks for 5+ years" in e for e in exp.evidence)
    assert any("Quality, Engineer" in e for e in exp.evidence)  # "Senior" is not a relevance word


def test_years_shortfall_is_a_gap():
    desc = "Requirements\n- 15+ years of experience in quality engineering\n"
    exp = _component(match_job(profile(), job(desc), DEFAULT_WEIGHTS), "experience")
    assert exp.score < 1 and any("short of the stated 15 years" in g for g in exp.gaps)


def test_cv_without_dates_is_not_measured_but_explained():
    undated = QUALITY_CV.replace(" — Jan 2019 to Present", "").replace(" — Jun 2015 to Dec 2018", "")
    exp = _component(match_job(profile(undated), job(), DEFAULT_WEIGHTS), "experience")
    assert any("no employment dates were found" in g for g in exp.gaps)


def test_unstated_requirements_are_not_assessed_and_weight_is_redistributed():
    desc = "Requirements\n- Python and SQL for reporting\n- Build dashboards for finance teams\n"
    r = match_job(profile(), job(desc, title="Analyst"), DEFAULT_WEIGHTS)
    edu = _component(r, "education")
    assert not edu.assessed and edu.note == "The job states no education requirement."
    assert r.assessed_weight < 100
    assert sum(r.effective_weight(c) for c in r.components) == pytest.approx(100, abs=0.2)
    assert r.effective_weight(edu) == 0


def test_mandatory_gap_flagged_even_when_score_is_high():
    desc = ("Requirements\n- Must have FMEA and SPC experience\n- Kubernetes certification is essential\n"
            "- Minitab and SQL\n")
    r = match_job(profile(), job(desc), DEFAULT_WEIGHTS)
    assert [g.requirement for g in r.mandatory_gaps] == ["Kubernetes"]
    assert r.mandatory_gaps[0].evidence == "Kubernetes certification is essential"


def test_mandatory_degree_gap_respects_equivalent_experience():
    no_degree = QUALITY_CV.replace("BSc Mechanical Engineering — Example University — 2015", "Example College")
    strict = match_job(profile(no_degree), job("Requirements\n- A master's degree is required\n"), DEFAULT_WEIGHTS)
    assert any("Master" in g.requirement for g in strict.mandatory_gaps)
    lenient = match_job(profile(no_degree),
                        job("Requirements\n- A bachelor's degree is required, or equivalent experience\n"),
                        DEFAULT_WEIGHTS)
    assert not lenient.mandatory_gaps
    assert _component(lenient, "education").score == 0.5


def test_lower_degree_gets_partial_credit():
    edu = _component(match_job(profile(), job("Requirements\n- Master's degree in Engineering\n"), DEFAULT_WEIGHTS),
                     "education")
    assert edu.score == 0.5 and "highest level found in your CV is a bachelor's degree" in edu.gaps[0]


def test_short_description_has_low_confidence_and_is_ranked_last():
    good, short = job(), job(SHORT_JOB, title="Quality Engineer")
    ranked = rank_jobs(profile(), [short, good], DEFAULT_WEIGHTS)
    assert ranked[0].job is good and ranked[-1].job is short
    assert ranked[-1].confidence == "Low"
    assert any("short" in reason for reason in ranked[-1].confidence_reasons)


def test_weights_change_the_score():
    skills_only = ScoringWeights(ats=0, required_skills=100, experience=0, responsibilities=0, education=0, keywords=0)
    r = match_job(profile(), job(), skills_only)
    assert r.score == round(100 * _component(r, "required_skills").score)


def test_unrelated_job_scores_low():
    desc = ("Responsibilities\n- Design marketing campaigns for consumer brands\n- Write social media content\n"
            "Requirements\n- 3+ years of experience in digital marketing\n- SEO and HubSpot\n")
    r = match_job(profile(), job(desc, title="Marketing Manager"), DEFAULT_WEIGHTS)
    assert r.score < 50
    assert set(r.missing_required_skills) >= {"SEO", "HubSpot"}


def test_check_yourself_requirements_do_not_change_score():
    base = "Requirements\n- Python and SQL\n"
    plain = match_job(profile(), job(base), DEFAULT_WEIGHTS)
    with_visa = match_job(profile(), job(base + "- Must be eligible to work in Canada\n"), DEFAULT_WEIGHTS)
    assert with_visa.check_yourself and not plain.check_yourself
    assert with_visa.score == plain.score


def _active_cv(sha: str = "abc") -> ActiveCV:
    return ActiveCV("cv.pdf", 100, sha, datetime.now(timezone.utc), extraction(QUALITY_CV))


def _outcome(jobs) -> SearchOutcome:
    from src.jobs.models import SearchQuery
    return SearchOutcome(SearchQuery(keywords="quality"), (ProviderResult("himalayas", "Himalayas", "ok", tuple(jobs)),),
                         datetime.now(timezone.utc), unique_jobs=tuple(jobs))


def test_ranked_matches_are_cached_until_inputs_change():
    state: dict = {}
    outcome = _outcome([job()])
    first = ranked_matches(state, _active_cv(), outcome, DEFAULT_WEIGHTS)
    assert ranked_matches(state, _active_cv(), outcome, DEFAULT_WEIGHTS) is first
    assert ranked_matches(state, _active_cv("other"), outcome, DEFAULT_WEIGHTS) is not first
    clear_matches(state)
    assert state == {}


def test_match_profile_is_cached_per_cv_and_cleared():
    from src.services.matching import match_profile

    state: dict = {}
    first = match_profile(state, _active_cv())
    assert match_profile(state, _active_cv()) is first
    assert match_profile(state, _active_cv("new")) is not first
    clear_matches(state)
    assert state == {}
