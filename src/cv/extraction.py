"""Secure CV validation and text extraction for PDF and DOCX files.

Files are processed entirely in memory — nothing is written to disk — and the
raw bytes are not retained after extraction. CV content is never logged.
"""

from __future__ import annotations

import hashlib
import io
import re
import unicodedata
import zipfile
from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Literal

import pymupdf as fitz
from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

FileKind = Literal["pdf", "docx"]

SUPPORTED_EXTENSIONS: dict[str, FileKind] = {".pdf": "pdf", ".docx": "docx"}
_PDF_MAGIC = b"%PDF-"
_ZIP_MAGIC = b"PK\x03\x04"

# A page with fewer extractable characters than this, but with images, is treated as scanned.
_MIN_CHARS_PER_TEXT_PAGE = 40
# Below this many characters in total, the document cannot be analysed meaningfully.
MIN_USEFUL_CHARS = 200
_MAX_PDF_PAGES = 30
_MAX_DOCX_UNCOMPRESSED = 50 * 1024 * 1024  # guard against zip bombs


class CVError(Exception):
    """Base class for user-facing CV processing errors (messages are safe to display)."""


class CVValidationError(CVError):
    """The uploaded file is not an acceptable CV file."""


class CVExtractionError(CVError):
    """The file looked valid but its text could not be extracted."""


@dataclass(frozen=True)
class ExtractionResult:
    text: str
    kind: FileKind
    page_count: int | None  # PDFs only; DOCX has no fixed pagination
    needs_ocr: bool = False
    scanned_pages: tuple[int, ...] = ()  # 1-based page numbers that appear to be images
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def char_count(self) -> int:
        return len(self.text)

    @property
    def word_count(self) -> int:
        return len(self.text.split())

    @property
    def is_usable(self) -> bool:
        return not self.needs_ocr and self.char_count >= MIN_USEFUL_CHARS


# --- Validation ------------------------------------------------------------

_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._ -]+")


def sanitize_filename(name: str, max_length: int = 120) -> str:
    """Reduce a user-supplied filename to a safe display name (no paths or control characters)."""
    base = PurePath(name.replace("\\", "/")).name
    base = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode("ascii")
    base = _UNSAFE_CHARS.sub("_", base).strip(" ._") or "cv"
    if len(base) > max_length:
        stem, dot, ext = base.rpartition(".")
        base = (stem[: max_length - len(ext) - 1] + "." + ext) if dot and len(ext) <= 5 else base[:max_length]
    return base


def detect_kind(filename: str) -> FileKind:
    ext = PurePath(filename).suffix.lower()
    if ext == ".doc":
        raise CVValidationError(
            "Legacy Word .doc files are not supported. Save the CV as .docx or PDF and upload it again."
        )
    if ext not in SUPPORTED_EXTENSIONS:
        raise CVValidationError("Unsupported file type. Upload your CV as a PDF or DOCX file.")
    return SUPPORTED_EXTENSIONS[ext]


def validate_upload(filename: str, data: bytes, max_bytes: int) -> FileKind:
    """Check extension, size and file signature. Returns the file kind."""
    kind = detect_kind(filename)
    if not data:
        raise CVValidationError("The file is empty. Choose a CV file that contains your document.")
    if len(data) > max_bytes:
        limit_mb = max_bytes / (1024 * 1024)
        raise CVValidationError(f"The file is larger than the {limit_mb:g} MB limit. Upload a smaller file.")

    if kind == "pdf" and not data.lstrip()[:8].startswith(_PDF_MAGIC):
        raise CVValidationError("This file has a .pdf extension but is not a valid PDF document.")
    if kind == "docx":
        if not data.startswith(_ZIP_MAGIC):
            raise CVValidationError("This file has a .docx extension but is not a valid Word document.")
        _check_docx_container(data)
    return kind


def _check_docx_container(data: bytes) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = set(zf.namelist())
            total = sum(info.file_size for info in zf.infolist())
    except zipfile.BadZipFile as exc:
        raise CVValidationError("The Word document is damaged and cannot be opened.") from exc
    if "word/document.xml" not in names:
        raise CVValidationError("This file is not a Word document (word/document.xml is missing).")
    if total > _MAX_DOCX_UNCOMPRESSED:
        raise CVValidationError("The Word document is unusually large when unpacked and was rejected.")


# --- Text normalisation ----------------------------------------------------

_BULLETS = re.compile(r"^[ \t]*[•●▪■◦○·‣⁃–\-\*]+[ \t]+", re.MULTILINE)
_MULTI_BLANK = re.compile(r"\n{3,}")
_INLINE_WS = re.compile(r"[ \t  -​]+")


def normalize_text(text: str) -> str:
    """Normalise Unicode, whitespace and bullet glyphs while preserving line/section breaks."""
    text = unicodedata.normalize("NFKC", text).replace("\x00", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\f", "\n\n")
    text = _BULLETS.sub("- ", text)
    lines = [_INLINE_WS.sub(" ", line).strip() for line in text.split("\n")]
    text = "\n".join(lines)
    return _MULTI_BLANK.sub("\n\n", text).strip()


# --- PDF -------------------------------------------------------------------

def _extract_pdf(data: bytes) -> ExtractionResult:
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:  # PyMuPDF raises several error types for damaged files
        raise CVExtractionError("The PDF is damaged or unreadable and could not be opened.") from exc

    with doc:
        if doc.needs_pass:
            raise CVExtractionError("The PDF is password-protected. Remove the password and upload it again.")
        if doc.page_count == 0:
            raise CVExtractionError("The PDF has no pages.")
        if doc.page_count > _MAX_PDF_PAGES:
            raise CVValidationError(
                f"The PDF has {doc.page_count} pages. CVs longer than {_MAX_PDF_PAGES} pages are not accepted."
            )

        page_texts: list[str] = []
        scanned: list[int] = []
        try:
            for number, page in enumerate(doc, start=1):
                text = page.get_text("text", sort=True)
                if len(text.strip()) < _MIN_CHARS_PER_TEXT_PAGE and page.get_images(full=False):
                    scanned.append(number)
                page_texts.append(text)
        except Exception as exc:
            raise CVExtractionError("Text could not be read from the PDF.") from exc
        page_count = doc.page_count

    text = normalize_text("\n\n".join(page_texts))
    warnings: list[str] = []
    needs_ocr = False
    if scanned and len(scanned) == page_count:
        needs_ocr = True
    elif scanned and len(text) < MIN_USEFUL_CHARS:
        needs_ocr = True
    elif scanned:
        pages = ", ".join(map(str, scanned))
        warnings.append(
            f"Page(s) {pages} appear to be scanned images; their content could not be read and is not "
            "included in the analysis."
        )
    if not needs_ocr and not text:
        raise CVExtractionError("No text could be found in this PDF.")
    return ExtractionResult(text, "pdf", page_count, needs_ocr, tuple(scanned), tuple(warnings))


# --- DOCX ------------------------------------------------------------------

def _iter_docx_blocks(document):
    """Yield paragraphs and tables in document order (python-docx lists them separately)."""
    body = document.element.body
    for child in body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            yield Paragraph(child, document)
        elif tag == "tbl":
            yield Table(child, document)


def _table_lines(table: Table) -> list[str]:
    lines = []
    for row in table.rows:
        cells: list[str] = []
        for cell in row.cells:
            value = cell.text.strip()
            if value and (not cells or cells[-1] != value):  # merged cells repeat their text
                cells.append(value)
        if cells:
            lines.append(" | ".join(cells))
    return lines


def _extract_docx(data: bytes) -> ExtractionResult:
    try:
        document = Document(io.BytesIO(data))
    except Exception as exc:
        raise CVExtractionError("The Word document is damaged or unreadable and could not be opened.") from exc

    lines: list[str] = []
    warnings: list[str] = []
    try:
        # Contact details are often placed in the page header.
        header_lines = []
        for section in document.sections:
            for p in section.header.paragraphs:
                if p.text.strip() and p.text.strip() not in header_lines:
                    header_lines.append(p.text.strip())
        lines.extend(header_lines)
        if header_lines:
            lines.append("")

        for block in _iter_docx_blocks(document):
            if isinstance(block, Paragraph):
                text = block.text
                style = (block.style.name if block.style is not None else "") or ""
                if style.lower().startswith(("heading", "title")) and lines and lines[-1] != "":
                    lines.append("")  # keep a visible boundary before headings
                if style.lower().startswith("list") and text.strip():
                    text = "- " + text.strip()
                lines.append(text)
            else:
                lines.extend(_table_lines(block))
                lines.append("")
    except Exception as exc:
        raise CVExtractionError("Text could not be read from the Word document.") from exc

    has_images = any(
        rel.reltype.endswith("/image") for rel in document.part.rels.values()
    )
    text = normalize_text("\n".join(lines))
    if not text:
        if has_images:
            return ExtractionResult("", "docx", None, needs_ocr=True)
        raise CVExtractionError("The Word document does not contain any text.")
    if has_images and len(text) < MIN_USEFUL_CHARS:
        warnings.append("The document contains images; any text inside images cannot be read.")
    return ExtractionResult(text, "docx", None, warnings=tuple(warnings))


# --- Public API ------------------------------------------------------------

def extract_text(data: bytes, kind: FileKind) -> ExtractionResult:
    result = _extract_pdf(data) if kind == "pdf" else _extract_docx(data)
    if not result.needs_ocr and result.char_count < MIN_USEFUL_CHARS:
        result = ExtractionResult(
            result.text, result.kind, result.page_count, result.needs_ocr, result.scanned_pages,
            result.warnings + (
                "Very little text was found. The analysis may be unreliable; check that this is your full CV.",
            ),
        )
    return result


def fingerprint(data: bytes) -> str:
    """SHA-256 of the file, used to detect re-uploads of the same document."""
    return hashlib.sha256(data).hexdigest()
