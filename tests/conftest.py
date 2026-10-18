"""Test-wide safety: no test may reach the internet or read a developer's .env file."""

import pytest

from config.settings import get_settings


@pytest.fixture(autouse=True)
def _offline_isolated_settings(monkeypatch):
    monkeypatch.setenv("CAREERMATCH_OFFLINE_MODE", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
