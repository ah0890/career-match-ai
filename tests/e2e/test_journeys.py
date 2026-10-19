"""End-to-end journeys in a real browser against the running app.

Opt-in (they start a server and need Playwright's Chromium):
    set CAREERMATCH_RUN_E2E=1 and run ``python -m pytest tests/e2e``.
The app runs in offline mode with a temporary database, so nothing leaves the computer and
no real data is touched. Job search needs live sources and is covered by the integration tests.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(os.environ.get("CAREERMATCH_RUN_E2E") != "1", reason="set CAREERMATCH_RUN_E2E=1 to run"),
]
playwright = pytest.importorskip("playwright.sync_api")
ROOT = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def app_url(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("e2e")
    port = _free_port()
    env = {**os.environ, "CAREERMATCH_OFFLINE_MODE": "true",
           "CAREERMATCH_DATABASE_URL": f"sqlite:///{(tmp / 'e2e.db').as_posix()}",
           "CAREERMATCH_CV_STORAGE_DIR": str(tmp / "cv_files"), "CAREERMATCH_CV_AI_ENABLED": "false"}
    proc = subprocess.Popen([sys.executable, "-m", "streamlit", "run", "app.py", "--server.port", str(port),
                             "--server.headless", "true"], cwd=ROOT, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://localhost:{port}"
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                break
        except OSError:
            time.sleep(0.5)
    else:
        proc.kill()
        pytest.fail("The app did not start within 60 seconds.")
    yield url
    proc.terminate()
    proc.wait(timeout=20)


@pytest.fixture
def page(app_url):
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch()
        pg = browser.new_page(viewport={"width": 1280, "height": 1800})
        errors: list[str] = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.errors = errors  # type: ignore[attr-defined]
        yield pg
        browser.close()


def _no_errors(pg) -> None:
    assert pg.locator("[data-testid='stException']").count() == 0
    assert not pg.errors


@pytest.fixture(scope="module")
def cv_pdf(tmp_path_factory) -> Path:
    from tests.fixtures.cv_factory import make_text_pdf

    path = tmp_path_factory.mktemp("cv") / "Alex Example CV.pdf"
    path.write_bytes(make_text_pdf())
    return path


def test_every_page_opens_without_errors(page, app_url):
    from src.ui.navigation import PAGES

    for spec in PAGES:
        page.goto(f"{app_url}/{spec.url_path}")
        page.wait_for_selector("h1", timeout=30000)
        _no_errors(page)


def test_cv_journey_upload_analyse_compare_and_save_version(page, app_url, cv_pdf):
    page.goto(f"{app_url}/cv-analysis")
    page.locator("input[type=file]").set_input_files(str(cv_pdf))
    page.wait_for_selector("text=Prioritised improvements", timeout=60000)
    # The upload triggers a rerun that briefly rebuilds the page, so wait for the result itself.
    page.wait_for_selector(".cm-badge:has-text('Text extracted')", timeout=30000)

    page.get_by_role("tab", name="Compare with a job").click()
    page.get_by_label("Job title (optional)").fill("Quality Engineer")
    page.get_by_label("Job description").fill("Requirements\n- Must have FMEA and SPC\n- IATF 16949 is essential\n"
                                              + "Quality engineering in automotive manufacturing. " * 10)
    page.get_by_role("button", name="Compare with my CV").click()
    page.wait_for_selector("text=Improve your CV for this job", timeout=30000)
    assert page.get_by_text("IATF 16949: not found in your CV").first.is_visible()

    # Navigate in-app: a full page load starts a new session, and the CV lives only in the session.
    page.get_by_role("link", name="CV Studio").click()
    page.wait_for_selector("text=Your original stays untouched", timeout=30000)
    _no_errors(page)


def test_tracker_journey_feeds_the_dashboard(page, app_url):
    page.goto(f"{app_url}/application-tracker")
    page.wait_for_selector("text=Add an application manually", timeout=30000)
    page.get_by_text("Add an application manually").click()
    page.get_by_label("Job title").fill("Supplier Quality Engineer")
    page.get_by_label("Company").fill("Example Devices")
    page.get_by_role("button", name="Add to tracker").click()
    page.wait_for_selector("text=Total applications", timeout=30000)  # the summary appears once one exists

    page.goto(f"{app_url}/dashboard")
    page.wait_for_selector("text=Active applications", timeout=30000)
    page.wait_for_selector(".js-plotly-plot", timeout=30000)  # charts render after the page text
    _no_errors(page)
