"""CV workspace storage: original documents, the master CV, versions, revisions and job links.

Rules this module enforces:
* an original upload is stored once (encrypted) and never modified;
* the master CV and every version are independent copies — editing one never changes another;
* revisions are immutable snapshots; restoring creates a new revision instead of rewriting history;
* a version used by a job application cannot be deleted (it can be archived), and the exact
  revision submitted with an application stays retrievable.
"""

from __future__ import annotations

import difflib
import json
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.cv.session import process_upload
from src.db.models import Application, CVDoc, CVFile, CVRevision, CVSource
from src.workspace import files
from src.workspace.document import CVDocument
from src.workspace.importer import import_text, style_from_docx, style_from_pdf
from src.workspace.style import FormatSettings, StyleProfile

MAX_NAME = 160


class WorkspaceError(ValueError):
    """A user-correctable problem; the message is safe to show."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def load(doc: CVDoc | CVRevision) -> CVDocument:
    return CVDocument.model_validate_json(doc.content_json)


def load_format(doc: CVDoc | CVRevision) -> FormatSettings:
    return FormatSettings.model_validate_json(doc.format_json)


def _clean_name(name: str) -> str:
    name = " ".join((name or "").split())[:MAX_NAME]
    if len(name) < 2:
        raise WorkspaceError("Give the version a name of at least 2 characters.")
    return name


# --- original documents -------------------------------------------------------------------

def import_source(session: Session, filename: str, data: bytes, *, max_bytes: int,
                  ocr_text: str | None = None) -> CVSource:
    """Validate, extract and store an uploaded CV (encrypted). Raises CVError for unusable files."""
    cv = process_upload(filename, data, max_bytes)
    text = (ocr_text or cv.extraction.text).strip()
    try:
        style = style_from_pdf(data) if cv.extraction.kind == "pdf" else style_from_docx(data)
    except Exception:  # styling is a nicety; never block an import over it
        style = StyleProfile.default()
    source = CVSource(filename=cv.filename, kind=cv.extraction.kind, size_bytes=cv.size_bytes, sha256=cv.sha256,
                      blob=files.put(data), page_count=cv.extraction.page_count, extracted_text=text,
                      needs_ocr=cv.extraction.needs_ocr and not ocr_text, style_json=style.model_dump_json())
    session.add(source)
    session.flush()
    return source


def list_sources(session: Session) -> list[CVSource]:
    return list(session.scalars(select(CVSource).order_by(CVSource.imported_at.desc())))


def source_bytes(source: CVSource) -> bytes:
    if not source.blob:
        raise WorkspaceError("The original file of this import was deleted.")
    return files.get(source.blob)


def delete_source_file(session: Session, source_id: int) -> None:
    """Delete an original file. CVs built from it keep their own content."""
    source = session.get(CVSource, source_id)
    if source is not None:
        files.remove(source.blob)
        session.delete(source)


def source_style(source: CVSource | None) -> StyleProfile:
    if source is None or not source.style_json:
        return StyleProfile.default()
    return StyleProfile.model_validate_json(source.style_json)


# --- documents & revisions -------------------------------------------------------------------

def get_master(session: Session) -> CVDoc | None:
    return session.scalar(select(CVDoc).where(CVDoc.role == "master"))


def get_doc(session: Session, doc_id: int) -> CVDoc:
    doc = session.get(CVDoc, doc_id)
    if doc is None:
        raise WorkspaceError("That CV no longer exists.")
    return doc


def list_docs(session: Session, include_archived: bool = False) -> list[CVDoc]:
    query = select(CVDoc).order_by((CVDoc.role != "master"), CVDoc.updated_at.desc())
    if not include_archived:
        query = query.where(CVDoc.status != "archived")
    return list(session.scalars(query))


def latest_revision(session: Session, doc: CVDoc) -> CVRevision | None:
    return session.scalar(select(CVRevision).where(CVRevision.doc_id == doc.id)
                          .order_by(CVRevision.number.desc()).limit(1))


def get_revision(session: Session, doc: CVDoc, number: int) -> CVRevision:
    rev = session.scalar(select(CVRevision).where(CVRevision.doc_id == doc.id, CVRevision.number == number))
    if rev is None:
        raise WorkspaceError(f"Revision {number} does not exist.")
    return rev


def snapshot(session: Session, doc: CVDoc, kind: str, note: str) -> CVRevision:
    """Record the current content as a new immutable revision (skipped if nothing changed)."""
    last = latest_revision(session, doc)
    if last is not None and last.content_json == doc.content_json and last.format_json == doc.format_json:
        return last
    number = (last.number if last else 0) + 1
    rev = CVRevision(doc_id=doc.id, number=number, kind=kind, note=note[:300],
                     content_json=doc.content_json, format_json=doc.format_json)
    session.add(rev)
    session.flush()
    return rev


def save(session: Session, doc: CVDoc, content: CVDocument | None = None, fmt: FormatSettings | None = None, *,
         revision: tuple[str, str] | None = None) -> CVDoc:
    """Persist the working copy; with ``revision=(kind, note)`` also record a revision."""
    if content is not None:
        doc.content_json = content.model_dump_json()
    if fmt is not None:
        doc.format_json = fmt.model_dump_json()
    doc.updated_at = _now()
    session.flush()
    if revision:
        snapshot(session, doc, *revision)
    return doc


def create_master(session: Session, source: CVSource | None, content: CVDocument | None = None) -> CVDoc:
    """Create the master CV from an import — or, if one exists, replace its content as a new revision."""
    content = content or import_text(source.extracted_text if source else "")
    fmt = FormatSettings.from_profile(source_style(source)) if source else FormatSettings()
    master = get_master(session)
    note = f"Imported from {source.filename}" if source else "Created"
    if master is None:
        master = CVDoc(role="master", name="Master CV", status="draft", source_id=source.id if source else None,
                       content_json=content.model_dump_json(), format_json=fmt.model_dump_json())
        session.add(master)
        session.flush()
        snapshot(session, master, "import", note)
        return master
    snapshot(session, master, "edit", "Before importing a replacement CV")  # the previous content stays restorable
    master.source_id = source.id if source else master.source_id
    return save(session, master, content, fmt, revision=("import", note))


def unique_name(session: Session, name: str) -> str:
    taken = set(session.scalars(select(CVDoc.name)))
    if name not in taken:
        return name
    n = 2
    while f"{name} ({n})" in taken:
        n += 1
    return f"{name} ({n})"


def default_version_name(target_title: str | None, company: str | None) -> str:
    title = " ".join((target_title or "").split())
    if title and company:
        return f"{title} — {company}"
    return f"{title} — Optimised CV" if title else "Optimised CV"


def create_version(session: Session, base: CVDoc, *, name: str | None = None, target_title: str | None = None,
                   target_company: str | None = None, job_description: str | None = None,
                   job_key: str | None = None) -> CVDoc:
    """A new, independent copy of ``base`` (usually the master)."""
    rev = latest_revision(session, base) or snapshot(session, base, "edit", "Saved")
    version = CVDoc(
        role="version", status="draft",
        name=unique_name(session, _clean_name(name or default_version_name(target_title, target_company))),
        target_title=(target_title or "").strip()[:300] or None, target_company=(target_company or "").strip()[:300] or None,
        job_description=(job_description or "").strip()[:60000] or None, job_key=job_key,
        source_id=base.source_id, parent_id=base.id, parent_revision=rev.number,
        content_json=base.content_json, format_json=base.format_json)
    session.add(version)
    session.flush()
    snapshot(session, version, "import", f"Created from {base.name} (revision {rev.number})")
    return version


def rename(session: Session, doc: CVDoc, name: str) -> None:
    name = _clean_name(name)
    if name != doc.name:
        doc.name = unique_name(session, name)
        doc.updated_at = _now()


def duplicate(session: Session, doc: CVDoc) -> CVDoc:
    copy = create_version(session, doc, name=f"{doc.name} (copy)", target_title=doc.target_title,
                          target_company=doc.target_company, job_description=doc.job_description, job_key=doc.job_key)
    return copy


def set_archived(session: Session, doc: CVDoc, archived: bool) -> None:
    if doc.role == "master":
        raise WorkspaceError("The master CV cannot be archived.")
    doc.status = "archived" if archived else "draft"
    doc.updated_at = _now()


def applications_using(session: Session, doc: CVDoc) -> list[Application]:
    return list(session.scalars(select(Application).where(Application.cv_doc_id == doc.id)))


def delete(session: Session, doc: CVDoc) -> None:
    """Delete a version and its generated PDFs. The master and original uploads are never affected."""
    if doc.role == "master":
        raise WorkspaceError("The master CV cannot be deleted.")
    used = applications_using(session, doc)
    if used:
        raise WorkspaceError(f"This CV is linked to {len(used)} job application(s), which must keep the exact CV "
                             "that was sent. Archive it instead.")
    for f in session.scalars(select(CVFile).where(CVFile.doc_id == doc.id)):
        files.remove(f.blob)
    session.delete(doc)


def restore(session: Session, doc: CVDoc, number: int) -> CVRevision:
    """Bring back an earlier revision's content as a new revision; nothing is overwritten."""
    old = get_revision(session, doc, number)
    snapshot(session, doc, "edit", "Before restoring")
    doc.content_json, doc.format_json = old.content_json, old.format_json
    doc.updated_at = _now()
    session.flush()
    return snapshot(session, doc, "restore", f"Restored revision {number}")


def update_contact_from_master(session: Session, version: CVDoc) -> None:
    """Copy the master's contact details into a version (the user chooses which versions)."""
    master = get_master(session)
    if master is None or version.role == "master":
        return
    content = load(version)
    content.contact = load(master).contact.model_copy()
    save(session, version, content, revision=("edit", "Contact details updated from the master CV"))


def children(session: Session, doc: CVDoc) -> list[CVDoc]:
    return list(session.scalars(select(CVDoc).where(CVDoc.parent_id == doc.id, CVDoc.status != "archived")))


# --- comparison --------------------------------------------------------------------------

@dataclass(frozen=True)
class Change:
    kind: str  # added / removed / changed
    where: str
    before: str
    after: str


def compare(a: CVDocument, b: CVDocument) -> list[Change]:
    """What changed from ``a`` to ``b``, matched by the stable ids that versions inherit from their parent."""
    changes: list[Change] = []
    for field in ("name", "headline", "email", "phone", "location"):
        x, y = getattr(a.contact, field), getattr(b.contact, field)
        if x != y:
            changes.append(Change("changed" if x and y else ("added" if y else "removed"), f"Contact: {field}", x, y))
    old = {i.id: (s, e, i) for s, e, i in a.iter_items()}
    new = {i.id: (s, e, i) for s, e, i in b.iter_items()}
    for item_id, (s, e, i) in new.items():
        where = f"{s.title}" + (f" · {e.title}" if e.title else "")
        if item_id not in old:
            changes.append(Change("added", where, "", i.text))
        elif old[item_id][2].text != i.text:
            changes.append(Change("changed", where, old[item_id][2].text, i.text))
        elif old[item_id][2].hidden != i.hidden:
            changes.append(Change("changed", where, i.text + (" (shown)" if i.hidden else ""),
                                  i.text + (" (left out)" if i.hidden else "")))
    for item_id, (s, e, i) in old.items():
        if item_id not in new:
            changes.append(Change("removed", f"{s.title}" + (f" · {e.title}" if e.title else ""), i.text, ""))
    old_entries = {e.id: e for s in a.sections for e in s.entries}
    for s in b.sections:
        for e in s.entries:
            if e.id in old_entries and old_entries[e.id].header != e.header:
                changes.append(Change("changed", f"{s.title} · heading", old_entries[e.id].header, e.header))
    if [s.title for s in a.sections] != [s.title for s in b.sections]:
        changes.append(Change("changed", "Section order", " → ".join(s.title for s in a.sections),
                              " → ".join(s.title for s in b.sections)))
    return changes


def text_diff(a: CVDocument, b: CVDocument) -> str:
    return "\n".join(difflib.unified_diff(a.to_text().splitlines(), b.to_text().splitlines(),
                                          "before", "after", lineterm="", n=1))


# --- job applications --------------------------------------------------------------------

def suggest_for_job(session: Session, job_key: str | None, title: str | None, company: str | None) -> CVDoc | None:
    """The version made for this job, else one for the same company and role, else the master."""
    docs = list_docs(session)
    if job_key:
        for d in docs:
            if d.job_key == job_key:
                return d
    norm = lambda s: " ".join((s or "").lower().split())  # noqa: E731
    for d in docs:
        if d.role == "version" and norm(d.target_company) and norm(d.target_company) == norm(company) \
                and norm(d.target_title) == norm(title):
            return d
    return get_master(session)


def select_for_application(session: Session, app: Application, doc: CVDoc) -> None:
    """Link a CV to an application (after the user confirmed). A submitted application pins the current revision."""
    from src.tracker.repository import APPLIED
    app.cv_doc_id = doc.id
    app.cv_revision_number = None
    if app.status in APPLIED:
        app.cv_revision_number = (latest_revision(session, doc) or snapshot(session, doc, "edit", "Saved")).number


def pin_for_submission(session: Session, app: Application) -> None:
    """Called when an application is submitted: remember exactly which revision was sent."""
    if app.cv_doc_id and app.cv_revision_number is None:
        doc = session.get(CVDoc, app.cv_doc_id)
        if doc is not None:
            app.cv_revision_number = (latest_revision(session, doc) or snapshot(session, doc, "edit", "Saved")).number


def application_cv(session: Session, app: Application) -> tuple[CVDoc, CVRevision | None] | None:
    """For future application workflows: the CV (and pinned revision) an application uses."""
    if not app.cv_doc_id:
        return None
    doc = session.get(CVDoc, app.cv_doc_id)
    if doc is None:
        return None
    rev = get_revision(session, doc, app.cv_revision_number) if app.cv_revision_number else None
    return doc, rev


def counts(session: Session) -> dict[str, int]:
    rows = session.execute(select(CVDoc.status, func.count()).where(CVDoc.role == "version").group_by(CVDoc.status))
    return {status: n for status, n in rows}


def to_json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)
