from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[2] / "app.py"
pytestmark = pytest.mark.integration


def test_app_starts_on_dashboard_without_errors():
    at = AppTest.from_file(str(APP), default_timeout=30).run()
    assert not at.exception
    rendered = " ".join(str(el.value) for el in at.get("html"))
    assert "Dashboard" in rendered
