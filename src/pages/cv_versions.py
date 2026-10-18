"""CV Versions — separate CVs for different career paths."""

from __future__ import annotations

from src.ui.components import Feature, page_header
from src.ui.layouts import empty_page_body


def render() -> None:
    page_header(
        "CV Versions",
        "Keep tailored CVs for different career paths and choose which one to match against.",
        eyebrow="Track",
    )
    empty_page_body(
        empty_title="No CV versions yet",
        empty_message="Versions are created from uploaded CVs. Your original CV is never overwritten.",
        cta_label="Go to CV Analysis", cta_target="cv-analysis", cta_key="cvv_cta",
        features_title="What you will be able to do",
        features=[
            Feature("Organise by career path", "Name and describe versions such as Technical, Management "
                    "or Quality Assurance."),
            Feature("Compare versions", "See how different versions score against the same job."),
            Feature("Delete with confidence", "Clear controls remove a version and its associated records."),
        ],
    )
