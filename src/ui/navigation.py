"""Application page registry and navigation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import streamlit as st

from src.ui.components import empty_state, page_header


@dataclass(frozen=True)
class PageSpec:
    title: str
    url_path: str
    icon: str  # Material Symbols name, rendered by Streamlit (one consistent icon family)
    subtitle: str


PAGES: tuple[PageSpec, ...] = (
    PageSpec("Dashboard", "dashboard", ":material/space_dashboard:",
             "Your job search at a glance."),
    PageSpec("Find Jobs", "find-jobs", ":material/travel_explore:",
             "Search configured job sources for relevant vacancies."),
    PageSpec("CV Analysis", "cv-analysis", ":material/description:",
             "Upload your CV and review its structure and ATS compatibility."),
    PageSpec("Job Matches", "job-matches", ":material/fact_check:",
             "Ranked opportunities with explainable match scores."),
    PageSpec("Company Intelligence", "company-intelligence", ":material/domain:",
             "Sourced research on employers you are considering."),
    PageSpec("Interview Preparation", "interview-preparation", ":material/school:",
             "Prioritised questions and study plans for each role."),
    PageSpec("Application Tracker", "application-tracker", ":material/view_kanban:",
             "Track every application from saved to offer."),
    PageSpec("CV Versions", "cv-versions", ":material/folder_copy:",
             "Maintain separate CVs for different career paths."),
    PageSpec("Settings", "settings", ":material/settings:",
             "Providers, scoring, search defaults and privacy."),
)


def _placeholder(spec: PageSpec) -> Callable[[], None]:
    def render() -> None:
        page_header(spec.title, spec.subtitle)
        empty_state(
            "This section is not available yet",
            "It is being built in an upcoming milestone. Nothing is shown here until "
            "it is backed by real functionality and data.",
        )

    render.__name__ = f"page_{spec.url_path.replace('-', '_')}"
    return render


def build_navigation(renderers: dict[str, Callable[[], None]] | None = None):
    """Create the Streamlit navigation object. Unimplemented pages get an honest placeholder."""
    renderers = renderers or {}
    pages = [
        st.Page(
            renderers.get(spec.url_path, _placeholder(spec)),
            title=spec.title,
            icon=spec.icon,
            url_path=spec.url_path,
            default=(i == 0),
        )
        for i, spec in enumerate(PAGES)
    ]
    return st.navigation(pages, position="sidebar")
