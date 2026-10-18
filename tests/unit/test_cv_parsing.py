from datetime import date

import pytest

from src.cv.extraction import normalize_text
from src.cv.parsing import (
    analyse_bullets, estimate_experience_years, extract_contact, extract_date_ranges, looks_like_heading,
    match_heading, parse_cv,
)
from tests.fixtures.cv_factory import SAMPLE_CV_TEXT

TODAY = date(2026, 10, 1)


@pytest.mark.parametrize("line,key", [
    ("EXPERIENCE", "experience"), ("Work Experience:", "experience"), ("Professional Experience", "experience"),
    ("Employment History", "experience"), ("EDUCATION & TRAINING", "education"),
    ("Education and Training", "education"), ("Core Competencies", "skills"), ("Skills & Competencies", "skills"),
    ("Profile", "summary"), ("Licenses and Certifications", "certifications"), ("Key Projects", "projects"),
])
def test_heading_variants(line, key):
    assert match_heading(line) == key


@pytest.mark.parametrize("line", [
    "Experience in leading teams of 20 engineers.",
    "Skills include Python and SQL and many other interesting technologies",
    "education@example.com",
    "",
])
def test_sentences_are_not_headings(line):
    assert match_heading(line) is None


def test_looks_like_heading_detects_nonstandard_caps():
    assert looks_like_heading("CAREER HIGHLIGHTS")
    assert not looks_like_heading("Senior Engineer")
    assert not looks_like_heading("ISO 9001")


def test_parse_sample_cv():
    parsed = parse_cv(normalize_text(SAMPLE_CV_TEXT), today=TODAY)
    assert parsed.section_keys == ("summary", "experience", "education", "skills")
    assert parsed.name_guess == "Alex Example"
    assert parsed.contact.emails == ("alex.example@example.com",)
    assert parsed.contact.phones
    assert len(parsed.date_ranges) == 2
    assert parsed.date_ranges[0].is_current
    assert 11 <= parsed.experience_years_estimate <= 11.5
    assert {"Python", "SQL", "FMEA", "ISO 9001"} <= {s.name for s in parsed.skills}
    assert parsed.bullets.total == 3
    assert parsed.bullets.action_verb == 3


def test_cv_without_headings_still_parses_and_explains():
    parsed = parse_cv("Jane Sample\njane@example.com\nWorked at Example Ltd 2018 - 2022 using Python.", today=TODAY)
    assert parsed.sections == ()
    assert any("No standard section headings" in n for n in parsed.notes)
    assert parsed.date_ranges and parsed.experience_years_estimate > 0
    assert any("whole CV" in n for n in parsed.notes)


def test_repeated_sections_are_merged():
    text = "EXPERIENCE\nRole A\n\nSKILLS\nPython\n\nEXPERIENCE\nRole B"
    parsed = parse_cv(text, today=TODAY)
    assert parsed.section_keys == ("experience", "skills")
    assert "Role A" in parsed.section("experience").text and "Role B" in parsed.section("experience").text


def test_missing_name_is_none_not_invented():
    assert parse_cv("EXPERIENCE\nEngineer 2019 - 2020", today=TODAY).name_guess is None


@pytest.mark.parametrize("text,count,style", [
    ("Jan 2019 - Mar 2021", 1, "month-name"),
    ("January 2019 to Present", 1, "month-name"),
    ("01/2019 – 03/2021", 1, "numeric"),
    ("2019 - 2021", 1, "year-only"),
    ("Jan 2019 - 03/2021", 1, "mixed"),
    ("Founded in 2019", 0, None),
])
def test_date_ranges(text, count, style):
    ranges = extract_date_ranges(text, TODAY)
    assert len(ranges) == count
    if count:
        assert ranges[0].style == style


def test_date_range_rejects_end_before_start():
    assert extract_date_ranges("2021 - 2019", TODAY) == []


def test_experience_years_counts_overlap_once():
    ranges = extract_date_ranges("Jan 2018 - Dec 2019\nJan 2019 - Dec 2020", TODAY)
    assert estimate_experience_years(ranges) == 3.0


def test_phone_detection_ignores_date_ranges():
    contact = extract_contact("Alex\n2015 - 2019\n+44 20 7946 0000")
    assert contact.phones == ("+44 20 7946 0000",)


def test_contact_links():
    contact = extract_contact("Alex | linkedin.com/in/alex-example | https://example.com/portfolio.")
    assert "linkedin.com/in/alex-example" in contact.links
    assert "https://example.com/portfolio" in contact.links


def test_bullet_analysis():
    stats = analyse_bullets([
        "Led a team of 12 engineers",
        "Reduced scrap by 18% in six months",
        "I was responsible for reports",
        "word " * 45,
    ])
    assert stats.total == 4
    assert stats.action_verb == 2
    assert stats.quantified == 2
    assert stats.first_person == 1
    assert stats.too_long == 1
