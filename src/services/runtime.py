"""Process-wide shared resources for the Streamlit app."""

from __future__ import annotations

import streamlit as st

from config.settings import Settings
from src.providers.http import ProviderHttp


@st.cache_resource(show_spinner=False)
def _http(timeout_s: float, offline: bool) -> ProviderHttp:
    return ProviderHttp(timeout_s=timeout_s, offline=offline)


def get_http(settings: Settings) -> ProviderHttp:
    """One shared client per configuration, so caches and rate limits apply across sessions."""
    return _http(settings.http_timeout_s, settings.offline_mode)
