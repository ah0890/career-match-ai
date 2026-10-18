"""Page-level layout patterns shared by several pages."""

from __future__ import annotations

from typing import Sequence

import streamlit as st

from src.ui.components import Feature, empty_state, feature_grid, section_header
from src.ui.navigation import go_to


def call_to_action(
    label: str, target: str, *, key: str, primary: bool = True, icon: str | None = None, stretch: bool = False
) -> None:
    """A button that navigates to another page."""
    if st.button(label, key=key, type="primary" if primary else "secondary", icon=icon,
                 width="stretch" if stretch else "content"):
        go_to(target)


def empty_page_body(
    *,
    empty_title: str,
    empty_message: str,
    cta_label: str | None = None,
    cta_target: str | None = None,
    cta_key: str = "cta",
    features_title: str | None = None,
    features: Sequence[Feature] = (),
) -> None:
    """Honest empty state + next action + a short description of what the page will hold."""
    empty_state(empty_title, empty_message)
    if cta_label and cta_target:
        st.write("")
        _, mid, _ = st.columns([2, 1, 2])
        with mid:
            call_to_action(cta_label, cta_target, key=cta_key, icon=":material/arrow_forward:", stretch=True)
    if features:
        section_header(features_title or "What you will find here")
        feature_grid(features)
