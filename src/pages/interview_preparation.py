"""Interview Preparation — prioritised questions and study plans."""

from __future__ import annotations

from src.ui.components import Feature, page_header
from src.ui.layouts import empty_page_body


def render() -> None:
    page_header(
        "Interview Preparation",
        "Prepare for each role with prioritised questions, study guidance and progress tracking.",
        eyebrow="Prepare",
    )
    empty_page_body(
        empty_title="No preparation plans yet",
        empty_message="Select a job from your matches to generate a tailored preparation package based on "
                      "the job description, your CV and verified company research.",
        cta_label="View job matches", cta_target="job-matches", cta_key="ip_cta",
        features_title="What each plan includes",
        features=[
            Feature("Prioritised questions", "Technical, behavioural, company-specific and HR questions "
                    "ranked Very High to Lower, with the reason for each priority."),
            Feature("STAR preparation", "Guidance for structuring answers around your genuine experience — "
                    "examples are never invented for you."),
            Feature("Study plan and progress", "A suggested study sequence with Not Started, Preparing and "
                    "Prepared tracking."),
        ],
    )
