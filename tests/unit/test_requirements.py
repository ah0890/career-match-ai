"""Job requirement extraction, degree detection and text helpers."""

import pytest

from src.matching.education import DegreeLevel, highest_degree, lowest_degree
from src.matching.requirements import extract_requirements
from src.matching.text import content_stems, stem
from tests.fixtures.match_factory import QUALITY_JOB, SHORT_JOB, job


def _skills(req):
    return {s.name: s for s in req.skills}


def test_required_and_preferred_skills_follow_section_headings():
    s = _skills(extract_requirements(job()))
    assert s["Minitab"].required and s["SQL"].required
    assert not s["Six Sigma"].required and not s["Tableau"].required


def test_mandatory_cue_marks_skills_essential():
    s = _skills(extract_requirements(job()))
    assert s["FMEA"].mandatory and s["Statistical Process Control"].mandatory
    assert not s["Minitab"].mandatory
    assert s["FMEA"].evidence == "Must have FMEA and SPC experience"


def test_benefits_section_does_not_create_skill_requirements():
    assert "Kubernetes" not in _skills(extract_requirements(job()))


def test_preferred_cue_inside_requirements_section_wins():
    req = extract_requirements(job("Requirements\n- Python\n- Experience with Docker is a plus\n"))
    s = _skills(req)
    assert s["Python"].required and not s["Docker"].required


def test_source_tags_count_as_required_skills():
    req = extract_requirements(job("Build data pipelines.", tags=("python", "airflow")))
    s = _skills(req)
    assert s["Python"].required and s["Airflow"].required and s["Python"].evidence == ""


@pytest.mark.parametrize("text, expected", [
    ("At least 5 years of experience in quality engineering", (5, None)),
    ("3-5 years experience with SQL", (3, 5)),
    ("You have 7+ years' experience leading teams", (7, None)),
    ("Five years of relevant experience", (5, None)),
    ("Experience: minimum 4 years", (4, None)),
    ("Python developer for 3 projects", None),
])
def test_years_of_experience(text, expected):
    exp = extract_requirements(job(f"Requirements\n- {text}\n")).experience
    assert (None if exp is None else (exp.min_years, exp.max_years)) == expected


def test_years_not_about_experience_are_ignored():
    req = extract_requirements(job("About us\nWe were founded 25 years ago.\nRequirements\n- Python\n"))
    assert req.experience is None


def test_headline_years_is_smallest_required_minimum():
    desc = ("Requirements\n- 3+ years of experience in data analysis\n- 5+ years of experience with Excel is a plus\n")
    exp = extract_requirements(job(desc)).experience
    assert exp.min_years == 3 and exp.required


def test_education_requirement_and_equivalent():
    edu = extract_requirements(job("Requirements\n- Bachelor's or Master's degree in Engineering, or equivalent "
                                   "experience\n")).education
    assert edu.level is DegreeLevel.BACHELOR and edu.allows_equivalent


@pytest.mark.parametrize("text", [
    "Give 360-degree feedback to peers", "You will have a high degree of autonomy",
    "Strong MS Excel skills", "Office in Boston, MA", "Certified Scrum Master",
])
def test_degree_false_positives(text):
    assert lowest_degree(text) is None


@pytest.mark.parametrize("text, level", [
    ("BSc Mechanical Engineering — Example University", DegreeLevel.BACHELOR),
    ("MSc Data Science, Example University", DegreeLevel.MASTER),
    ("MS in Computer Science", DegreeLevel.MASTER),
    ("PhD in Physics", DegreeLevel.DOCTORATE),
    ("Higher National Diploma in Electrical Engineering", DegreeLevel.DIPLOMA),
])
def test_cv_degree_levels(text, level):
    assert highest_degree(f"EDUCATION\n{text}").level is level


def test_highest_degree_prefers_higher_level():
    assert highest_degree("BSc Physics — 2010\nMSc Physics — 2012").level is DegreeLevel.MASTER


def test_responsibilities_from_section():
    req = extract_requirements(job())
    assert len(req.responsibilities) == 4
    assert req.responsibilities[0].startswith("Lead root cause analysis")


def test_responsibilities_without_headings_use_action_sentences():
    req = extract_requirements(job("We are a fictional company. Develop reporting dashboards for sales teams. "
                                   "Manage the monthly forecasting process. Great benefits."))
    assert req.responsibilities == ("Develop reporting dashboards for sales teams.",
                                    "Manage the monthly forecasting process.")


def test_unverifiable_requirements_are_reported_with_evidence():
    req = extract_requirements(job())
    assert ("Right to work / work authorisation", "Right to work in the UK is required") in req.unverifiable


def test_structure_and_short_description_notes():
    req = extract_requirements(job(QUALITY_JOB))
    assert req.structured and not req.notes
    short = extract_requirements(job(SHORT_JOB))
    assert not short.structured and "short description" in short.notes[0]


def test_keywords_exclude_benefits_text_and_skill_names():
    req = extract_requirements(job())
    assert "gym" not in req.keywords and "minitab" not in req.keywords
    assert "quality" in req.keywords


def test_stemming_matches_word_forms():
    assert stem("managed") == stem("manage") == stem("manages") == stem("managing")
    assert stem("supplies") == stem("supply")
    assert stem("Led") == "lead"
    assert content_stems("root-cause analysis") == ["root", "caus", "analysi"]
