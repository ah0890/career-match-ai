"""Test-wide safety: no test may reach the internet, read a developer's .env file or touch the real database."""

import pytest

from config.settings import get_settings


@pytest.fixture(autouse=True)
def _offline_isolated_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("CAREERMATCH_OFFLINE_MODE", "true")
    monkeypatch.setenv("CAREERMATCH_DATABASE_URL", f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    monkeypatch.setenv("CAREERMATCH_API_DATABASE_URL", f"sqlite:///{(tmp_path / 'api.db').as_posix()}")
    get_settings.cache_clear()
    # Never touch the developer's real credential store: tests get a throwaway key file.
    from src.mail import vault
    monkeypatch.setattr(vault, "_keyring_get", lambda: None)
    monkeypatch.setattr(vault, "_keyring_set", lambda value: False)
    monkeypatch.setattr(vault, "KEY_FILE", tmp_path / "mail_key")
    yield
    get_settings.cache_clear()
