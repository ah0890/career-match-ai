"""CV Analysis — structure, ATS compatibility and improvements."""

from __future__ import annotations

from src.ui.components import Feature, page_header
from src.ui.layouts import empty_page_body


def render() -> None:
    page_header(
        "CV Analysis",
        "Check how clearly your CV communicates your experience and how reliably software can read it.",
        eyebrow="Discover",
    )
    empty_page_body(
        empty_title="No CV uploaded yet",
        empty_message="Secure PDF and DOCX upload is being added next. Your CV will be processed on this "
                      "computer and never sent to an external service by default.",
        features_title="What the analysis will include",
        features=[
            Feature("ATS compatibility", "A transparent score out of 100 with a breakdown of how it was "
                    "calculated. It estimates readability, not the result of any specific employer's ATS."),
            Feature("Structure and formatting", "Section detection, heading consistency, date formats and "
                    "formatting patterns that commonly cause parsing problems."),
            Feature("Skills and keywords", "Technical and soft skills found in your CV, and keyword gaps "
                    "against a target job description."),
            Feature("Prioritised improvements", "Practical suggestions based only on what your CV actually "
                    "contains — never invented achievements."),
        ],
    )
