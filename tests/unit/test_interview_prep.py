"""Interview preparation plans."""

from datetime import datetime, timezone

from src.company.models import CompanyProfile, Fact, Source
from src.interview.prep import build_prep_plan, plan_markdown
from src.matching.engine import match_job
from src.ui.interview_view import question_card_html
from tests.fixtures.match_factory import DEFAULT_WEIGHTS, QUALITY_CV, job, profile

DESC = ("Responsibilities\n- Lead root cause analysis on production lines\n- Coordinate internal audits\n"
        "Requirements\n- Kubernetes is essential\n- Must have FMEA and SPC\n- Minitab and SQL\n"
        "- Strong communication\n- Eligible to work in the UK\n")


def _plan(cv=QUALITY_CV, description=DESC, researched=None, **kw):
    p = profile(cv)
    return build_prep_plan(p, match_job(p, job(description, **kw), DEFAULT_WEIGHTS), researched)


def _q(plan, starts):
    return next(q for q in plan.questions if q.text.startswith(starts))


def test_questions_are_ordered_by_likelihood():
    order = {"Very likely": 0, "Likely": 1, "Possible": 2}
    plan = _plan()
    ranks = [order[q.likelihood] for q in plan.questions]
    assert ranks == sorted(ranks)
    assert plan.questions[0].text == "Tell me about yourself."


def test_skill_questions_quote_the_job_and_link_cv_material_by_alias():
    spc = _q(_plan(), "Take us through how you applied Statistical Process Control")
    assert spc.likelihood == "Very likely" and "states it as essential" in spc.why
    assert any("SPC dashboards" in m for m in spc.cv_material)


def test_soft_skills_get_behavioural_questions_not_gap_questions():
    plan = _plan()
    comm = _q(plan, "Tell me about a time you demonstrated Communication")
    assert comm.kind == "Behavioural" and "Situation" in comm.guidance
    assert not any("Communication" in q.text for q in plan.by_kind("Gap"))


def test_gap_questions_are_honest():
    gap = _q(_plan(), "The role requires Kubernetes")
    assert gap.kind == "Gap" and gap.likelihood == "Very likely" and gap.cv_material == ()
    assert "say so honestly" in gap.guidance


def test_responsibility_questions_use_cv_or_say_none_found():
    plan = _plan()
    rca = _q(plan, "This role involves: “Lead root cause analysis")
    assert any("root-cause analysis" in m for m in rca.cv_material)
    audits = _q(plan, "This role involves: “Coordinate internal audits")
    assert audits.cv_material == () and "no clearly related line" in audits.guidance


def test_company_question_uses_researched_facts_only_for_the_same_company():
    src = Source("Wikidata", "https://www.wikidata.org/wiki/Q901", "CC0 1.0")
    company = CompanyProfile("Q901", "Example Devices", None, None, (Fact("Industry", "medical technology", src),),
                             (), None, (), datetime.now(timezone.utc))
    q = _q(_plan(researched=company), "Why do you want to work at Example Devices")
    assert q.kind == "Company" and "industry: medical technology" in q.guidance
    other = _q(_plan(researched=company, company="Other Co"), "Why do you want to work at Other Co")
    assert other.kind == "Motivation" and "Company Intelligence" in other.guidance


def test_questions_to_ask_include_unverifiable_requirements():
    asks = _plan().questions_to_ask
    assert any("right to work" in q for q in asks)
    assert asks[-1] == "What are the next steps in the process?"


def test_markdown_export_and_card_escape_content():
    plan = _plan()
    md = plan_markdown(plan)
    assert md.startswith("# Interview preparation: Senior Quality Engineer at Example Devices")
    assert "## Questions to ask" in md and "- [ ] " in md
    evil = _plan(description="Requirements\n- <script>alert(1)</script> Python is essential\n")
    assert all("<script>" not in question_card_html(q) for q in evil.questions)


def test_cv_without_bullets_uses_experience_lines():
    flat = "\n".join(line.removeprefix("- ") for line in QUALITY_CV.split("\n"))
    plan = _plan(flat)
    assert not plan.notes
    assert _q(plan, "Take us through how you applied FMEA").cv_material


def test_cv_without_bullets_or_experience_explains_missing_material():
    plan = _plan("Alex Example\nSKILLS\nFMEA, SPC, Minitab, SQL")
    assert "No bullet points" in plan.notes[0]
