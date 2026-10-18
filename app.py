"""CareerMatch AI — Streamlit entry point.

Run with:  streamlit run app.py
"""

from __future__ import annotations

import streamlit as st

from config.settings import PROJECT_ROOT, get_settings
from src.ui.navigation import build_navigation
from src.ui.theme import apply_theme


def main() -> None:
    settings = get_settings()
    st.set_page_config(
        page_title=settings.app_name,
        page_icon=str(PROJECT_ROOT / "assets" / "icon.svg"),
        layout="wide",
        initial_sidebar_state="auto",
    )
    apply_theme()
    st.logo(
        str(PROJECT_ROOT / "assets" / "logo.svg"),
        icon_image=str(PROJECT_ROOT / "assets" / "icon.svg"),
        size="large",
    )
    navigation = build_navigation()
    navigation.run()


main()
