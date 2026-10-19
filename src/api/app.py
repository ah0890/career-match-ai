"""CareerMatch AI backend API — accounts and per-account CV, job analysis, interview prep and tailoring.

Run locally with ``python -m src.api``. It listens on 127.0.0.1 only by default. Every route
except health, register and sign-in needs ``Authorization: Bearer <token>``.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, Response, UploadFile, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from config.settings import Settings, get_settings
from src.api import accounts, schemas, services
from src.api.db import api_session
from src.api.models import User, UserJob
from src.cv.extraction import CVError
from src.cv.session import process_upload
from src.interview.prep import build_prep_plan
from src.matching.improvements import improvement_plan
from src.tailoring.edits import apply_edits, suggest_edits
from src.tailoring.export import to_docx, to_pdf

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


def _db() -> Iterator[Session]:
    with api_session(get_settings().api_database_url) as session:
        yield session


DB = Annotated[Session, Depends(_db)]


def _bearer(authorization: Annotated[str | None, Header()] = None) -> str:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in to continue.",
                            headers={"WWW-Authenticate": "Bearer"})
    return token.strip()


def _current_user(session: DB, token: Annotated[str, Depends(_bearer)]) -> User:
    user = accounts.resolve_token(session, token)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Your session has expired. Sign in again.",
                            headers={"WWW-Authenticate": "Bearer"})
    return user


CurrentUser = Annotated[User, Depends(_current_user)]
Config = Annotated[Settings, Depends(get_settings)]


def _require_cv(session: Session, user: User):
    row = services.get_cv(session, user)
    if row is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Upload your CV first.")
    return row


def _job(session: Session, user: User, job_id: int) -> UserJob:
    try:
        return services.get_job(session, user, job_id)
    except services.NotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found.") from None


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="CareerMatch AI API", version="1.0", docs_url="/api/docs", redoc_url=None,
                  openapi_url="/api/openapi.json")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.api_cors_origin_list,
        allow_origin_regex=r"^chrome-extension://[a-p]{32}$",  # unpacked or published Chrome extensions
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.middleware("http")
    async def _headers(request: Request, call_next):
        response = await call_next(request)
        for name, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response

    @app.exception_handler(RequestValidationError)
    async def _validation(_request: Request, exc: RequestValidationError):
        # Report which fields were wrong without echoing the submitted values back.
        problems = [{"field": ".".join(str(p) for p in e["loc"][1:]), "message": e["msg"]} for e in exc.errors()]
        return JSONResponse({"detail": "Some fields are missing or invalid.", "problems": problems}, status_code=422)

    # --- health and accounts ------------------------------------------------

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.post("/api/auth/register", status_code=status.HTTP_201_CREATED)
    def register(body: schemas.Credentials, session: DB, cfg: Config) -> dict:
        try:
            user = accounts.register(session, body.email, body.password)
        except accounts.AccountError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
        token = accounts.issue_token(session, user, cfg.api_token_days, body.client)
        return schemas.token_out(token, user.email, cfg.api_token_days)

    @app.post("/api/auth/login")
    def login(body: schemas.Credentials, session: DB, cfg: Config) -> dict:
        try:
            user = accounts.authenticate(session, body.email, body.password, cfg.api_max_failed_logins,
                                         cfg.api_lockout_minutes)
        except accounts.AccountError as exc:
            session.commit()  # keep the failed-attempt count even though the request fails
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from None
        token = accounts.issue_token(session, user, cfg.api_token_days, body.client)
        return schemas.token_out(token, user.email, cfg.api_token_days)

    @app.post("/api/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
    def logout(session: DB, token: Annotated[str, Depends(_bearer)]) -> Response:
        accounts.revoke_token(session, token)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get("/api/me")
    def me(user: CurrentUser, session: DB) -> dict:
        jobs = session.scalar(select(func.count()).select_from(UserJob).where(UserJob.user_id == user.id))
        return schemas.account_out(user.email, user.created_at, services.get_cv(session, user), jobs or 0)

    @app.delete("/api/me", status_code=status.HTTP_204_NO_CONTENT)
    def delete_me(user: CurrentUser, session: DB) -> Response:
        accounts.delete_account(session, user)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    # --- CV -----------------------------------------------------------------

    @app.put("/api/cv")
    async def upload_cv(user: CurrentUser, session: DB, cfg: Config, file: Annotated[UploadFile, File()],
                        consent: Annotated[bool, Form()] = False) -> dict:
        if not consent:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Confirm that you want your CV's text stored with your account.")
        data = await file.read(cfg.max_upload_bytes + 1)
        try:
            cv = process_upload(file.filename or "cv", data, cfg.max_upload_bytes)
        except CVError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
        if cv.extraction.needs_ocr or not cv.extraction.text.strip():
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "No text could be read from this CV. Upload a text-based PDF or a DOCX file.")
        row = services.store_cv(session, user, cv)
        return schemas.cv_out(row, services.profile_for(row))

    @app.get("/api/cv")
    def get_cv(user: CurrentUser, session: DB) -> dict:
        row = _require_cv(session, user)
        return schemas.cv_out(row, services.profile_for(row))

    @app.delete("/api/cv", status_code=status.HTTP_204_NO_CONTENT)
    def delete_cv(user: CurrentUser, session: DB) -> Response:
        services.delete_cv(session, user)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    # --- jobs ---------------------------------------------------------------

    def _analysis(session: Session, user: User, row: UserJob, cfg: Settings) -> dict:
        profile = services.profile_for(_require_cv(session, user))
        result, rec = services.analyse(profile, row, cfg)
        return schemas.analysis_out(row, result, rec, improvement_plan(profile, result))

    @app.post("/api/jobs/analyze")
    def analyze(body: schemas.JobIn, user: CurrentUser, session: DB, cfg: Config) -> dict:
        _require_cv(session, user)
        row = services.upsert_job(session, user, services.JobInput(**body.model_dump()))
        return _analysis(session, user, row, cfg)

    @app.get("/api/jobs")
    def jobs(user: CurrentUser, session: DB) -> dict:
        return {"jobs": [schemas.job_out(j) for j in services.list_jobs(session, user)]}

    @app.get("/api/jobs/{job_id}")
    def job(job_id: int, user: CurrentUser, session: DB, cfg: Config) -> dict:
        return _analysis(session, user, _job(session, user, job_id), cfg)

    @app.delete("/api/jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_job(job_id: int, user: CurrentUser, session: DB) -> Response:
        session.delete(_job(session, user, job_id))
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get("/api/jobs/{job_id}/interview")
    def interview(job_id: int, user: CurrentUser, session: DB, cfg: Config) -> dict:
        row = _job(session, user, job_id)
        profile = services.profile_for(_require_cv(session, user))
        result, _ = services.analyse(profile, row, cfg)
        return schemas.prep_out(build_prep_plan(profile, result))

    @app.get("/api/jobs/{job_id}/tailoring")
    def tailoring(job_id: int, user: CurrentUser, session: DB, cfg: Config) -> dict:
        row = _job(session, user, job_id)
        cv = _require_cv(session, user)
        result, _ = services.analyse(services.profile_for(cv), row, cfg)
        return {"job_id": row.id, "edits": schemas.edits_out(suggest_edits(cv.text, result))}

    @app.post("/api/jobs/{job_id}/tailored-cv")
    def tailored_cv(job_id: int, body: schemas.TailoredCVIn, user: CurrentUser, session: DB, cfg: Config):
        row = _job(session, user, job_id)
        cv = _require_cv(session, user)
        if body.text is not None:
            text = body.text
        else:
            result, _ = services.analyse(services.profile_for(cv), row, cfg)
            edits = suggest_edits(cv.text, result)
            unknown = set(body.accepted) - {e.id for e in edits}
            if unknown:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Some accepted changes are no longer suggested. "
                                    "Reload the suggestions and try again.")
            text = apply_edits(cv.text, edits, set(body.accepted))
        if not text.strip():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "The tailored CV is empty.")
        if body.format == "text":
            return {"text": text}
        name = services.download_name(row)
        data, mime = (to_docx(text), DOCX_MIME) if body.format == "docx" else (to_pdf(text), "application/pdf")
        return Response(data, media_type=mime,
                         headers={"Content-Disposition": f'attachment; filename="{name}.{body.format}"'})

    return app
