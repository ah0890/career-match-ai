import pytest

from src.matching.skills import TAXONOMY, extract_skills, skill_names


@pytest.mark.parametrize("text,expected", [
    ("Python, SQL and Power BI", {"Python", "SQL", "Power BI"}),
    ("Built REST APIs with FastAPI", {"REST APIs", "FastAPI"}),
    ("Experience with C++ and C#", {"C++", "C#"}),
    ("Skills: Python, R, SQL", {"Python", "R", "SQL"}),
    ("Deployed on k8s and AWS", {"Kubernetes", "AWS"}),
    ("Certified Six Sigma Green Belt; led 8D and PFMEA", {"Six Sigma", "8D", "FMEA"}),
    ("ISO 9001 and IATF 16949 audits", {"ISO 9001", "IATF 16949"}),
    ("Root-cause analysis on line stoppages", {"Root Cause Analysis"}),
])
def test_extracts_expected_skills(text, expected):
    assert expected <= skill_names(text)


@pytest.mark.parametrize("text,absent", [
    ("Worked with React and Redux", "R"),          # R must not match inside React
    ("JavaScript developer", "Java"),              # Java must not match JavaScript
    ("I excel at building relationships", "Excel"),  # verb, not the tool
    ("Managed R&D budget", "R"),
    ("We go to market quickly", "Go"),
    ("Grade C student", "C"),                       # prose single letter outside list context
])
def test_avoids_common_false_positives(text, absent):
    assert absent not in skill_names(text)


def test_results_are_distinct_and_categorised():
    matches = extract_skills("Python python PYTHON, SQL")
    names = [m.name for m in matches]
    assert names.count("Python") == 1
    assert all(m.category for m in matches)


def test_taxonomy_names_unique():
    names = [s.name for s in TAXONOMY]
    assert len(names) == len(set(names))
