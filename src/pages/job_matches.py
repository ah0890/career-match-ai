"""Job Matches — ranked, explainable opportunities."""

from __future__ import annotations

from src.ui.components import Feature, page_header
from src.ui.layouts import empty_page_body


def render() -> None:
    page_header(
        "Job Matches",
        "Jobs ranked by estimated compatibility with your CV, with the evidence behind every score.",
        eyebrow="Discover",
    )
    empty_page_body(
        empty_title="No matches yet",
        empty_message="Matches appear after you upload a CV and search for jobs. Each job will show its "
                      "score breakdown, matching evidence and missing requirements.",
        cta_label="Find jobs", cta_target="find-jobs", cta_key="jm_cta",
        features_title="How matching works",
        features=[
            Feature("Explainable scores", "Required skills, experience, responsibilities, education and "
                    "keywords are scored separately using configurable weights."),
            Feature("Recommendations", "APPLY, APPLY AFTER IMPROVEMENT or DON'T PRIORITIZE — guidance for "
                    "prioritising, not a prediction of being hired."),
            Feature("Mandatory requirements", "A clearly essential qualification that your CV does not "
                    "evidence is flagged, even when the overall score is high."),
        ],
    )
