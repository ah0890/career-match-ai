"""Job-specific CV improvement plan."""

from src.matching.engine import match_job
from src.matching.improvements import improvement_plan
from tests.fixtures.match_factory import DEFAULT_WEIGHTS, QUALITY_CV, job, profile


def _plan(cv=QUALITY_CV, description=None, **kw):
    p = profile(cv)
    j = job(description, **kw) if description else job(**kw)
    return improvement_plan(p, match_job(p, j, DEFAULT_WEIGHTS))


def _evidence(plan):
    return {s.name: s.evidence for s in plan.skills}


def test_skill_evidence_distinguishes_use_education_listing_and_absence():
    ev = _evidence(_plan())
    assert ev["FMEA"] == "shown in experience" and ev["PPAP"] == "shown in experience"
    assert ev["Mechanical Engineering"] == "shown in education"
    assert ev["Minitab"] == "listed only" and ev["SQL"] == "listed only"
    assert ev["ISO 13485"] == "not found"


def test_skills_are_ordered_gaps_first_and_keep_job_evidence():
    plan = _plan()
    assert plan.skills[0].evidence == "not found"
    fmea = next(s for s in plan.skills if s.name == "FMEA")
    assert fmea.essential and fmea.job_says == "Must have FMEA and SPC experience"


def test_suggestions_are_prioritised_and_never_supply_content():
    plan = _plan(description="Requirements\n- Kubernetes is essential\n- Minitab and SQL\n- Tableau is a plus\n")
    titles = [s.title for s in plan.suggestions]
    assert titles[0] == "Kubernetes: not found in your CV" and plan.suggestions[0].priority == "High"
    assert "If you have it" in plan.suggestions[0].detail
    assert "Show where you used skills you only list" in titles
    assert any(s.title == "Preferred skills not found" and s.priority == "Low" for s in plan.suggestions)
    assert "Only add what is true" in plan.note


def test_bullet_tips_target_relevant_bullets_without_inventing_numbers():
    cv = QUALITY_CV.replace("- Managed supplier PPAP submissions and incoming inspection plans.",
                            "- I was responsible for supplier PPAP submissions and incoming inspection plans.")
    plan = _plan(cv)
    tip = next(t for t in plan.bullet_tips if "PPAP" in t.bullet)
    assert "PPAP" in tip.related_to
    text = " ".join(tip.tips)
    assert "measurable result if you have one" in text and "Use only figures you can stand behind" in text
    assert "action verb" in text and "Remove “I”/“my”" in text
    assert all("18%" not in t for t in tip.tips)  # never borrows numbers from elsewhere


def test_quantified_action_bullets_need_no_tips():
    plan = _plan()
    assert all("Reduced scrap by 18%" not in t.bullet for t in plan.bullet_tips)


def test_keyword_gaps_quote_the_job():
    plan = _plan(description="Responsibilities\n- Own calibration of metrology equipment\n"
                             "- Plan calibration schedules and metrology audits\n")
    gaps = {k.keyword: k.job_says for k in plan.keyword_gaps}
    assert "calibration" in gaps and "calibration" in gaps["calibration"].lower()


def test_summary_suggestions():
    no_summary = QUALITY_CV.replace("PROFESSIONAL SUMMARY\nQuality engineer with experience in manufacturing process "
                                    "improvement and supplier quality management.\n", "")
    assert any(s.title == "Add a short summary for this kind of role" for s in _plan(no_summary).suggestions)
    other_role = _plan(title="Data Analyst")
    assert any("Data Analyst" in s.detail for s in other_role.suggestions if s.where == "Summary")
    assert not any(s.where == "Summary" for s in _plan().suggestions)  # summary already says "Quality engineer"
