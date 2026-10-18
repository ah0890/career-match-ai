"""Company Intelligence — sourced employer research."""

from __future__ import annotations

from src.ui.components import Feature, page_header
from src.ui.layouts import empty_page_body


def render() -> None:
    page_header(
        "Company Intelligence",
        "Research employers using credible public sources. Every important fact links to where it came from.",
        eyebrow="Prepare",
    )
    empty_page_body(
        empty_title="No companies researched yet",
        empty_message="Choose a job from your matches to research its employer. Facts that cannot be "
                      "verified are labelled as such rather than guessed.",
        cta_label="View job matches", cta_target="job-matches", cta_key="ci_cta",
        features_title="What each company profile covers",
        features=[
            Feature("Overview and history", "What the company does, where it operates and how it developed."),
            Feature("Products, projects and developments", "Current work and recent news, preferring "
                    "official and recent sources."),
            Feature("Leadership", "Publicly verifiable leaders with sources — or a clear note when they "
                    "could not be verified."),
            Feature("Relevance to your role", "Analysis connecting the employer to the vacancy, clearly "
                    "labelled as analysis rather than confirmed fact."),
        ],
    )
