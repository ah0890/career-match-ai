"""Backend API: accounts, tokens, per-user isolation, CV upload, job analysis and tailored downloads."""

import io

import pymupdf as fitz
import pytest
from docx import Document
from fastapi.testclient import TestClient

from config.settings import get_settings
from src.api import accounts
from src.api.app import create_app
from src.api.db import api_session
from src.api.models import AuthToken, UserCV
from tests.fixtures.cv_factory import make_docx, make_image_only_pdf
from tests.fixtures.match_factory import QUALITY_CV, QUALITY_JOB

PASSWORD = "correct horse battery"


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        yield c


def _register(client, email="alex@example.com", password=PASSWORD):
    r = client.post("/api/auth/register", json={"email": email, "password": password})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _store_quality_cv(headers):
    """Store the synthetic CV directly (its DOCX round trip is covered by the upload test)."""
    with api_session(get_settings().api_database_url) as s:
        token = headers["Authorization"].split()[1]
        user = accounts.resolve_token(s, token)
        s.add(UserCV(user_id=user.id, filename="cv.pdf", kind="pdf", page_count=1, sha256="a" * 64,
                     text=QUALITY_CV))


def _job(**kw):
    body = {"title": "Senior Quality Engineer", "company": "Example Devices", "description": QUALITY_JOB,
            "url": "https://example.com/jobs/1"}
    body.update(kw)
    return body


# --- accounts -------------------------------------------------------------

def test_health_and_security_headers(client):
    r = client.get("/api/health")
    assert r.json() == {"status": "ok"}
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["cache-control"] == "no-store"


def test_register_login_me_logout(client):
    headers = _register(client, "  Alex@Example.com ")
    me = client.get("/api/me", headers=headers).json()
    assert me == {"email": "alex@example.com", "created_at": me["created_at"], "has_cv": False, "saved_jobs": 0}
    r = client.post("/api/auth/login", json={"email": "alex@example.com", "password": PASSWORD,
                                            "client": "extension"})
    assert r.status_code == 200 and r.json()["token_type"] == "bearer"
    assert client.post("/api/auth/logout", headers=headers).status_code == 204
    assert client.get("/api/me", headers=headers).status_code == 401


def test_tokens_are_stored_only_as_hashes(client):
    headers = _register(client)
    token = headers["Authorization"].split()[1]
    with api_session(get_settings().api_database_url) as s:
        hashes = [t.token_hash for t in s.query(AuthToken)]
    assert token not in hashes and accounts.token_hash(token) in hashes


@pytest.mark.parametrize("email, password, message", [
    ("not-an-email", PASSWORD, "valid email"),
    ("a@example.com", "short", "at least 10"),
])
def test_register_validation(client, email, password, message):
    r = client.post("/api/auth/register", json={"email": email, "password": password})
    assert r.status_code == 400 and message in r.json()["detail"]


def test_duplicate_registration_is_refused(client):
    _register(client)
    r = client.post("/api/auth/register", json={"email": "ALEX@example.com", "password": PASSWORD})
    assert r.status_code == 400 and "already exists" in r.json()["detail"]


def test_wrong_password_and_unknown_email_give_the_same_message(client):
    _register(client)
    wrong = client.post("/api/auth/login", json={"email": "alex@example.com", "password": "wrong password!"})
    unknown = client.post("/api/auth/login", json={"email": "nobody@example.com", "password": PASSWORD})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"] == "Email or password is incorrect."


def test_repeated_failures_lock_the_account(client):
    _register(client)
    for _ in range(get_settings().api_max_failed_logins):
        client.post("/api/auth/login", json={"email": "alex@example.com", "password": "wrong password!"})
    r = client.post("/api/auth/login", json={"email": "alex@example.com", "password": PASSWORD})
    assert r.status_code == 401 and "Too many failed" in r.json()["detail"]


@pytest.mark.parametrize("header", [None, "Basic abc", "Bearer ", "Bearer not-a-real-token"])
def test_protected_routes_need_a_valid_token(client, header):
    headers = {"Authorization": header} if header else {}
    assert client.get("/api/jobs", headers=headers).status_code == 401


def test_password_hashes_are_salted_and_verifiable():
    a, b = accounts.hash_password(PASSWORD), accounts.hash_password(PASSWORD)
    assert a != b and PASSWORD not in a
    assert accounts.verify_password(PASSWORD, a) and not accounts.verify_password("other password", a)
    assert not accounts.verify_password(PASSWORD, "garbage")


def test_validation_errors_do_not_echo_submitted_values(client):
    r = client.post("/api/auth/register", json={"email": "a@example.com", "password": "x" * 500})
    assert r.status_code == 422 and "x" * 50 not in r.text


# --- CV ---------------------------------------------------------------------

def test_cv_upload_needs_consent_then_returns_analysis(client):
    headers = _register(client)
    files = {"file": ("cv.docx", make_docx(), "application/octet-stream")}
    r = client.put("/api/cv", headers=headers, files=files)
    assert r.status_code == 400 and "Confirm" in r.json()["detail"]
    r = client.put("/api/cv", headers=headers, files=files, data={"consent": "true"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "docx" and 0 <= body["ats"]["score"] <= 100 and body["skills"]
    assert "text" not in body  # the CV text is never echoed back
    assert client.get("/api/me", headers=headers).json()["has_cv"] is True
    assert client.delete("/api/cv", headers=headers).status_code == 204
    assert client.get("/api/cv", headers=headers).status_code == 409


def test_scanned_cv_is_rejected(client):
    headers = _register(client)
    r = client.put("/api/cv", headers=headers, data={"consent": "true"},
                   files={"file": ("cv.pdf", make_image_only_pdf(), "application/pdf")})
    assert r.status_code == 400 and "No text could be read" in r.json()["detail"]


# --- jobs -----------------------------------------------------------------

def test_analyze_needs_a_cv(client):
    headers = _register(client)
    r = client.post("/api/jobs/analyze", headers=headers, json=_job())
    assert r.status_code == 409 and r.json()["detail"] == "Upload your CV first."


def test_analyze_returns_explainable_match_and_saves_the_job(client):
    headers = _register(client)
    _store_quality_cv(headers)
    r = client.post("/api/jobs/analyze", headers=headers, json=_job())
    assert r.status_code == 200, r.text
    body = r.json()
    assert 0 <= body["score"] <= 100 and body["recommendation"]["label"]
    assert {c["key"] for c in body["components"]} >= {"required_skills", "experience"}
    assert "ISO 13485" in body["missing_required_skills"] or body["mandatory_gaps"]
    assert body["job"]["source_name"] == "example.com" and body["job"]["listing_url"] == "https://example.com/jobs/1"
    [saved] = client.get("/api/jobs", headers=headers).json()["jobs"]
    assert saved["match_score"] == body["score"]


def test_analysing_the_same_listing_again_updates_instead_of_duplicating(client):
    headers = _register(client)
    _store_quality_cv(headers)
    client.post("/api/jobs/analyze", headers=headers, json=_job())
    client.post("/api/jobs/analyze", headers=headers, json=_job(title="Quality Engineer II"))
    jobs = client.get("/api/jobs", headers=headers).json()["jobs"]
    assert len(jobs) == 1 and jobs[0]["title"] == "Quality Engineer II"


def test_unsafe_urls_are_dropped(client):
    headers = _register(client)
    _store_quality_cv(headers)
    body = client.post("/api/jobs/analyze", headers=headers,
                       json=_job(url="javascript:alert(1)", apply_url="https://user:pw@example.com/x")).json()
    assert body["job"]["listing_url"] is None and body["job"]["apply_url"] is None
    assert body["job"]["source_name"] == "Added by you"


def test_job_validation(client):
    headers = _register(client)
    _store_quality_cv(headers)
    assert client.post("/api/jobs/analyze", headers=headers, json=_job(description="too short")).status_code == 422
    assert client.post("/api/jobs/analyze", headers=headers, json={**_job(), "extra": 1}).status_code == 422


def test_users_cannot_see_each_others_jobs(client):
    alex = _register(client)
    _store_quality_cv(alex)
    job_id = client.post("/api/jobs/analyze", headers=alex, json=_job()).json()["job"]["id"]
    sam = _register(client, "sam@example.com")
    _store_quality_cv(sam)
    assert client.get("/api/jobs", headers=sam).json()["jobs"] == []
    for method, path in [("get", f"/api/jobs/{job_id}"), ("delete", f"/api/jobs/{job_id}"),
                         ("get", f"/api/jobs/{job_id}/interview"), ("get", f"/api/jobs/{job_id}/tailoring")]:
        assert getattr(client, method)(path, headers=sam).status_code == 404
    assert client.get(f"/api/jobs/{job_id}", headers=alex).status_code == 200


def test_interview_prep_and_job_deletion(client):
    headers = _register(client)
    _store_quality_cv(headers)
    job_id = client.post("/api/jobs/analyze", headers=headers, json=_job()).json()["job"]["id"]
    prep = client.get(f"/api/jobs/{job_id}/interview", headers=headers).json()
    assert prep["questions"][0]["text"] == "Tell me about yourself." and prep["checklist"]
    assert client.delete(f"/api/jobs/{job_id}", headers=headers).status_code == 204
    assert client.get(f"/api/jobs/{job_id}", headers=headers).status_code == 404


# --- tailoring ------------------------------------------------------------

def _tailoring(client, headers):
    job_id = client.post("/api/jobs/analyze", headers=headers, json=_job()).json()["job"]["id"]
    edits = client.get(f"/api/jobs/{job_id}/tailoring", headers=headers).json()["edits"]
    return job_id, edits


def test_tailoring_suggestions_and_text_preview(client):
    headers = _register(client)
    _store_quality_cv(headers)
    job_id, edits = _tailoring(client, headers)
    assert edits and all({"id", "before", "after", "needs_confirmation"} <= e.keys() for e in edits)
    none = client.post(f"/api/jobs/{job_id}/tailored-cv", headers=headers, json={"format": "text"}).json()
    assert none["text"] == QUALITY_CV  # nothing accepted → the original, unchanged
    accepted = [e["id"] for e in edits if not e["needs_confirmation"]]
    out = client.post(f"/api/jobs/{job_id}/tailored-cv", headers=headers,
                      json={"format": "text", "accepted": accepted}).json()["text"]
    assert out != QUALITY_CV and "Jan 2019 to Present" in out


def test_unknown_edit_ids_are_refused(client):
    headers = _register(client)
    _store_quality_cv(headers)
    job_id, _ = _tailoring(client, headers)
    r = client.post(f"/api/jobs/{job_id}/tailored-cv", headers=headers, json={"accepted": ["made-up"]})
    assert r.status_code == 400


def test_tailored_cv_downloads_as_docx_and_pdf(client):
    headers = _register(client)
    _store_quality_cv(headers)
    job_id, _ = _tailoring(client, headers)
    docx = client.post(f"/api/jobs/{job_id}/tailored-cv", headers=headers, json={"format": "docx"})
    assert docx.status_code == 200
    assert 'filename="cv-senior-quality-engineer-example-devices.docx"' in docx.headers["content-disposition"]
    assert Document(io.BytesIO(docx.content)).paragraphs[0].text == "Alex Example"
    pdf = client.post(f"/api/jobs/{job_id}/tailored-cv", headers=headers,
                      json={"format": "pdf", "text": "Alex Example\nSKILLS\nPython, SQL"})
    assert pdf.headers["content-type"] == "application/pdf"
    assert "Python, SQL" in fitz.open(stream=pdf.content, filetype="pdf")[0].get_text()


def test_deleting_the_account_removes_all_its_data(client):
    headers = _register(client)
    _store_quality_cv(headers)
    client.post("/api/jobs/analyze", headers=headers, json=_job())
    assert client.delete("/api/me", headers=headers).status_code == 204
    assert client.get("/api/me", headers=headers).status_code == 401
    with api_session(get_settings().api_database_url) as s:
        assert s.query(UserCV).count() == 0 and s.query(AuthToken).count() == 0


def test_cors_allows_chrome_extensions_only(client):
    ok = client.options("/api/health", headers={"Origin": "chrome-extension://" + "a" * 32,
                                                "Access-Control-Request-Method": "GET"})
    bad = client.options("/api/health", headers={"Origin": "https://evil.example",
                                                 "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == "chrome-extension://" + "a" * 32
    assert "access-control-allow-origin" not in bad.headers


def test_api_listens_on_loopback_by_default(monkeypatch):
    monkeypatch.delenv("CAREERMATCH_API_HOST", raising=False)
    get_settings.cache_clear()
    assert get_settings().api_host == "127.0.0.1"
