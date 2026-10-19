"""Generate, validate and keep the final CV files (PDF and DOCX).

A file is stored (encrypted) and offered for download only after it was generated *and* passed
validation. Each file records the exact CV revision it was made from and, when relevant, the
job application it belongs to.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import Application, CVDoc, CVFile
from src.workspace import files
from src.workspace import repository as repo
from src.workspace.render import (
    DOCX_MIME, PDF_MIME, RenderError, Validation, professional_filename, render_docx, render_pdf, validate_docx,
    validate_pdf,
)
from src.workspace.repository import WorkspaceError

MIME = {"pdf": PDF_MIME, "docx": DOCX_MIME}


@dataclass
class ExportResult:
    ok: bool
    kind: str
    validation: Validation
    data: bytes | None = None  # only when ok
    filename: str = ""
    file: CVFile | None = None
    pages: int | None = None
    fits_one_page: bool | None = None
    error: str | None = None


def generate(session: Session, doc: CVDoc, kind: str, *, one_page: bool = False, revision: int | None = None,
             application: Application | None = None, keep: bool = True) -> ExportResult:
    """Render ``doc`` (or one of its revisions) as ``kind`` and validate it. Stored only when valid."""
    if kind not in MIME:
        raise WorkspaceError("Choose PDF or DOCX.")
    if revision is None:
        rev = repo.latest_revision(session, doc) or repo.snapshot(session, doc, "edit", "Saved")
        if rev.content_json != doc.content_json or rev.format_json != doc.format_json:
            rev = repo.snapshot(session, doc, "edit", "Saved before download")
    else:
        rev = repo.get_revision(session, doc, revision)
    content, fmt = repo.load(rev), repo.load_format(rev)
    filename = professional_filename(content, doc.target_title or content.contact.headline, kind)
    try:
        if kind == "pdf":
            pdf = render_pdf(content, fmt, one_page=one_page)
            data, pages, fits = pdf.data, pdf.pages, pdf.fits_one_page
            validation = validate_pdf(data, content)
        else:
            data, pages, fits = render_docx(content, fmt), None, None
            validation = validate_docx(data, content)
    except RenderError as exc:
        return ExportResult(False, kind, Validation(kind, False, None, [("Generated", False, str(exc))]),
                            error=str(exc))
    except Exception:  # never show a download for a file that failed to build
        return ExportResult(False, kind, Validation(kind, False, None, [("Generated", False, "Unexpected error")]),
                            error="The document could not be generated. Try another template or page size.")
    if not validation.ok:
        return ExportResult(False, kind, validation, pages=pages, fits_one_page=fits,
                            error="The generated file did not pass its checks, so it is not offered for download: "
                                  + "; ".join(validation.problems))
    record = None
    if keep:
        record = CVFile(doc_id=doc.id, revision_number=rev.number, kind=kind, blob=files.put(data),
                        filename=filename, page_count=pages or 0, validation_json=json.dumps(validation.as_dict()),
                        format_json=rev.format_json, application_id=application.id if application else None)
        session.add(record)
        session.flush()
    return ExportResult(True, kind, validation, data, filename, record, pages, fits)


def list_files(session: Session, doc: CVDoc | None = None, *, application: Application | None = None) -> list[CVFile]:
    query = select(CVFile).order_by(CVFile.created_at.desc())
    if doc is not None:
        query = query.where(CVFile.doc_id == doc.id)
    if application is not None:
        query = query.where(CVFile.application_id == application.id)
    return list(session.scalars(query))


def file_bytes(record: CVFile) -> bytes:
    return files.get(record.blob)


def delete_file(session: Session, record: CVFile) -> None:
    files.remove(record.blob)
    session.delete(record)


def for_application(session: Session, app: Application) -> tuple[CVDoc, int, list[CVFile]] | None:
    """The CV linked to an application, the revision it uses and the files generated from that revision."""
    linked = repo.application_cv(session, app)
    if linked is None:
        return None
    doc, rev = linked
    number = rev.number if rev else (repo.latest_revision(session, doc).number if repo.latest_revision(session, doc)
                                     else 0)
    made = [f for f in list_files(session, doc) if f.revision_number == number]
    return doc, number, made
