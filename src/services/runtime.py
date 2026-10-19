"""Process-wide shared resources for the Streamlit app."""

from __future__ import annotations

import streamlit as st

from config.settings import Settings
from src.db.http_store import SqlHttpStore
from src.providers.http import ProviderHttp


@st.cache_resource(show_spinner=False)
def _http(timeout_s: float, offline: bool, database_url: str) -> ProviderHttp:
    return ProviderHttp(timeout_s=timeout_s, offline=offline, store=SqlHttpStore(database_url))


def get_http(settings: Settings) -> ProviderHttp:
    """One shared client per configuration, so caches and rate limits apply across sessions.

    Cached responses and daily request counts are also stored in the local database, so an app
    restart neither repeats requests nor resets a source's daily limit.
    """
    return _http(settings.http_timeout_s, settings.offline_mode, settings.database_url)
