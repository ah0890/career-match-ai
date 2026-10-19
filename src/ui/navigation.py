"""Application page registry and navigation."""

from __future__ import annotations

import importlib
from dataclasses import dataclass

import streamlit as st


@dataclass(frozen=True)
class PageSpec:
    title: str
    url_path: str
    icon: str  # Material Symbols name, rendered by Streamlit (one consistent icon family)
    module: str  # module under src.pages exposing render()
    section: str


PAGES: tuple[PageSpec, ...] = (
    PageSpec("Dashboard", "dashboard", ":material/space_dashboard:", "dashboard", "Overview"),
    PageSpec("Find Jobs", "find-jobs", ":material/travel_explore:", "find_jobs", "Discover"),
    PageSpec("CV Analysis", "cv-analysis", ":material/description:", "cv_analysis", "Discover"),
    PageSpec("Job Matches", "job-matches", ":material/fact_check:", "job_matches", "Discover"),
    PageSpec("Tailor CV", "tailor-cv", ":material/edit_document:", "tailor_cv", "Prepare"),
    PageSpec("Company Intelligence", "company-intelligence", ":material/domain:",
             "company_intelligence", "Prepare"),
    PageSpec("Interview Preparation", "interview-preparation", ":material/school:",
             "interview_preparation", "Prepare"),
    PageSpec("Application Tracker", "application-tracker", ":material/view_kanban:",
             "application_tracker", "Track"),
    PageSpec("CV Versions", "cv-versions", ":material/folder_copy:", "cv_versions", "Track"),
    PageSpec("Settings", "settings", ":material/settings:", "settings", "Account"),
)

_PAGES_BY_PATH = {p.url_path: p for p in PAGES}
_SESSION_KEY = "_cm_page_objects"


def get_spec(url_path: str) -> PageSpec:
    return _PAGES_BY_PATH[url_path]


def _renderer(spec: PageSpec):
    return importlib.import_module(f"src.pages.{spec.module}").render


def build_navigation():
    """Create the grouped Streamlit navigation; the first page is the default (served at '/')."""
    sections: dict[str, list] = {}
    objects = {}
    for i, spec in enumerate(PAGES):
        page = st.Page(
            _renderer(spec), title=spec.title, icon=spec.icon,
            url_path=spec.url_path, default=(i == 0),
        )
        objects[spec.url_path] = page
        sections.setdefault(spec.section, []).append(page)
    st.session_state[_SESSION_KEY] = objects
    return st.navigation(sections, position="sidebar")


def go_to(url_path: str) -> None:
    """Switch to another application page."""
    get_spec(url_path)  # validate
    st.switch_page(st.session_state[_SESSION_KEY][url_path])
