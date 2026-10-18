"""CareerMatch AI — Streamlit entry point.

Run with:  streamlit run app.py
"""

from __future__ import annotations

import streamlit as st

from config.settings import get_settings
from src.ui.navigation import build_navigation
from src.ui.theme import apply_theme


def main() -> None:
    settings = get_settings()
    st.set_page_config(
        page_title=settings.app_name,
        page_icon=":material/work:",
        layout="wide",
        initial_sidebar_state="auto",
    )
    apply_theme()
    with st.sidebar:
        st.markdown(f"**{settings.app_name}**")
        st.caption("Career intelligence & job matching")
    navigation = build_navigation()
    navigation.run()


main()
