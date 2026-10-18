"""Settings — current configuration, providers and privacy."""

from __future__ import annotations

from config.settings import get_settings
from src.ui.components import key_value, notice, page_header, section_header

WEIGHT_LABELS = {
    "ats": "ATS and CV compatibility",
    "required_skills": "Required skills",
    "experience": "Relevant experience",
    "responsibilities": "Job responsibilities",
    "education": "Education and certifications",
    "keywords": "Keywords and semantic relevance",
}


def _database_label(url: str) -> str:
    # Show the location only; never echo credentials that a non-SQLite URL might contain.
    if url.startswith("sqlite:///"):
        return f"SQLite — {url.removeprefix('sqlite:///')}"
    return url.split("://", 1)[0] + " (configured)"


def render() -> None:
    s = get_settings()
    page_header(
        "Settings",
        "Your current configuration. Values are read from environment variables or a local .env file; "
        "restart the app after changing them.",
        eyebrow="Account",
    )

    section_header("Job sources")
    notice(
        "No job-search providers are configured yet. Provider integrations are added only where an "
        "official API, authorised search service or permitted public feed exists.",
        tone="neutral",
    )

    section_header("Match scoring", "Weights must be non-negative and sum to 100.")
    weights = s.scoring_weights.as_dict()
    key_value([(WEIGHT_LABELS[k], f"{v:g}%") for k, v in weights.items()])

    section_header("Recommendation thresholds", "Prioritisation guidance only — not a prediction of hiring outcomes.")
    t = s.thresholds
    key_value([
        ("APPLY", f"{t.apply:g} – 100"),
        ("APPLY AFTER IMPROVEMENT", f"{t.improve:g} to below {t.apply:g}" if t.apply > t.improve else "Not used"),
        ("DON'T PRIORITIZE", f"Below {t.improve:g}"),
    ])

    section_header("Privacy and storage")
    key_value([
        ("Database", _database_label(s.database_url)),
        ("Maximum CV size", f"{s.max_upload_mb:g} MB"),
        ("External processing", "None — CVs are not sent to any external service"),
    ])
