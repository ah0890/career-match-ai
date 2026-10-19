"""Saved CV versions: keep, load, compare and delete.

Saving is always the user's explicit choice. Only the extracted text and a few facts about
the file are stored — never the original document.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import delete as sql_delete, select
from sqlalchemy.orm import Session

from src.cv.ats import ATSReport, analyse_cv
from src.cv.extraction import ExtractionResult
from src.cv.parsing import ParsedCV, parse_cv
from src.cv.session import ActiveCV
from src.db.models import CVVersion

MAX_VERSIONS = 20
STORAGE_NOTICE = (
    "Saving keeps this CV's extracted text in the local database on this computer (not the original file). "
    "The database file is not encrypted, so use disk encryption if others can access this computer. You can "
    "delete saved versions at any time."
)


class VersionError(ValueError):
    """A user-correctable problem; the message is safe to show."""


def _clean(text: str | None, limit: int) -> str | None:
    return " ".join((text or "").split())[:limit] or None


def save_version(session: Session, cv: ActiveCV, name: str, purpose: str | None = None) -> CVVersion:
    name_clean = _clean(name, 120)
    if not name_clean or len(name_clean) < 2:
        raise VersionError("Give the version a name of at least 2 characters.")
    if cv.extraction.needs_ocr or not cv.extraction.text.strip():
        raise VersionError("This CV's text could not be read, so it cannot be saved as a version.")
    if session.scalar(select(CVVersion).where(CVVersion.sha256 == cv.sha256)):
        raise VersionError("This exact CV is already saved as a version.")
    if session.scalar(select(CVVersion).where(CVVersion.name == name_clean)):
        raise VersionError(f"A version named “{name_clean}” already exists. Choose another name.")
    if len(list(session.scalars(select(CVVersion.id)))) >= MAX_VERSIONS:
        raise VersionError(f"You can keep up to {MAX_VERSIONS} versions. Delete one first.")
    parsed = parse_cv(cv.extraction.text)
    version = CVVersion(name=name_clean, purpose=_clean(purpose, 300), filename=cv.filename, kind=cv.extraction.kind,
                        page_count=cv.extraction.page_count, size_bytes=cv.size_bytes, sha256=cv.sha256,
                        text=cv.extraction.text, ats_score=analyse_cv(cv.extraction, parsed).score)
    session.add(version)
    session.flush()
    return version


def list_versions(session: Session) -> list[CVVersion]:
    return list(session.scalars(select(CVVersion).order_by(CVVersion.created_at.desc())))


def get_version(session: Session, version_id: int) -> CVVersion:
    version = session.get(CVVersion, version_id)
    if version is None:
        raise VersionError("That version no longer exists.")
    return version


def find_by_sha(session: Session, sha256: str) -> CVVersion | None:
    return session.scalar(select(CVVersion).where(CVVersion.sha256 == sha256))


def rename_version(session: Session, version_id: int, name: str, purpose: str | None) -> CVVersion:
    version = get_version(session, version_id)
    name_clean = _clean(name, 120)
    if not name_clean or len(name_clean) < 2:
        raise VersionError("Give the version a name of at least 2 characters.")
    clash = session.scalar(select(CVVersion).where(CVVersion.name == name_clean, CVVersion.id != version_id))
    if clash:
        raise VersionError(f"A version named “{name_clean}” already exists. Choose another name.")
    version.name, version.purpose = name_clean, _clean(purpose, 300)
    return version


def delete_version(session: Session, version_id: int) -> None:
    session.delete(get_version(session, version_id))


def delete_all(session: Session) -> int:
    return session.execute(sql_delete(CVVersion)).rowcount or 0


def extraction_of(version: CVVersion) -> ExtractionResult:
    return ExtractionResult(text=version.text, kind=version.kind, page_count=version.page_count)  # type: ignore[arg-type]


def as_active_cv(version: CVVersion) -> ActiveCV:
    """Use a saved version as the active CV for this session."""
    created = version.created_at if version.created_at.tzinfo else version.created_at.replace(tzinfo=timezone.utc)
    return ActiveCV(filename=f"{version.name} ({version.filename})", size_bytes=version.size_bytes,
                    sha256=version.sha256, uploaded_at=created or datetime.now(timezone.utc),
                    extraction=extraction_of(version))


@dataclass(frozen=True)
class ComponentDelta:
    label: str
    before: float
    after: float
    max_points: float


@dataclass(frozen=True)
class VersionComparison:
    ats_before: int
    ats_after: int
    components: tuple[ComponentDelta, ...]
    skills_added: tuple[str, ...]
    skills_removed: tuple[str, ...]
    words_before: int
    words_after: int
    sections_added: tuple[str, ...]
    sections_removed: tuple[str, ...]
    diff: tuple[str, ...]  # unified diff lines, capped


def _analyse(version: CVVersion) -> tuple[ParsedCV, ATSReport]:
    parsed = parse_cv(version.text)
    return parsed, analyse_cv(extraction_of(version), parsed)


def compare_versions(a: CVVersion, b: CVVersion, max_diff_lines: int = 400) -> VersionComparison:
    """How version ``b`` differs from version ``a``."""
    pa, ra = _analyse(a)
    pb, rb = _analyse(b)
    skills_a, skills_b = {s.name for s in pa.skills}, {s.name for s in pb.skills}
    sec_a, sec_b = set(pa.section_keys), set(pb.section_keys)
    diff = list(difflib.unified_diff(a.text.splitlines(), b.text.splitlines(), fromfile=a.name, tofile=b.name,
                                     lineterm="", n=1))
    if len(diff) > max_diff_lines:
        diff = diff[:max_diff_lines] + [f"… {len(diff) - max_diff_lines} more line(s) not shown"]
    return VersionComparison(
        ats_before=ra.score, ats_after=rb.score,
        components=tuple(ComponentDelta(ca.label, ca.score, cb.score, ca.max_score)
                         for ca, cb in zip(ra.components, rb.components)),
        skills_added=tuple(sorted(skills_b - skills_a)), skills_removed=tuple(sorted(skills_a - skills_b)),
        words_before=pa.word_count, words_after=pb.word_count,
        sections_added=tuple(sorted(sec_b - sec_a)), sections_removed=tuple(sorted(sec_a - sec_b)),
        diff=tuple(diff),
    )
