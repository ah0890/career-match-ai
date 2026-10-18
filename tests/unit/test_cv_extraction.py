import pytest

from src.cv.extraction import (
    CVExtractionError, CVValidationError, extract_text, fingerprint, normalize_text,
    sanitize_filename, validate_upload,
)
from src.cv.session import delete_active_cv, get_active_cv, process_upload, set_active_cv
from tests.fixtures import cv_factory as f

MB = 1024 * 1024


# --- Validation ------------------------------------------------------------

@pytest.mark.parametrize("name", ["cv.txt", "cv.png", "cv", "cv.pdf.exe", "resume.rtf"])
def test_unsupported_extensions_rejected(name):
    with pytest.raises(CVValidationError, match="PDF or DOCX"):
        validate_upload(name, b"%PDF-1.7", MB)


def test_legacy_doc_gets_specific_message():
    with pytest.raises(CVValidationError, match=r"\.doc files are not supported"):
        validate_upload("cv.doc", b"\xd0\xcf\x11\xe0", MB)


def test_extension_is_case_insensitive():
    assert validate_upload("CV.PDF", f.make_text_pdf(), MB) == "pdf"


def test_empty_file_rejected():
    with pytest.raises(CVValidationError, match="empty"):
        validate_upload("cv.pdf", b"", MB)


def test_oversized_file_rejected():
    with pytest.raises(CVValidationError, match="2 MB limit"):
        validate_upload("cv.pdf", b"%PDF-" + b"0" * (2 * MB), 2 * MB)


def test_pdf_extension_with_wrong_content_rejected():
    with pytest.raises(CVValidationError, match="not a valid PDF"):
        validate_upload("cv.pdf", b"hello world", MB)


def test_docx_extension_with_wrong_content_rejected():
    with pytest.raises(CVValidationError, match="not a valid Word"):
        validate_upload("cv.docx", b"%PDF-1.7 ...", MB)


def test_zip_that_is_not_docx_rejected():
    with pytest.raises(CVValidationError, match="not a Word document"):
        validate_upload("cv.docx", f.make_zip_without_document(), MB)


def test_damaged_zip_rejected():
    with pytest.raises(CVValidationError, match="damaged"):
        validate_upload("cv.docx", b"PK\x03\x04" + b"garbage" * 50, MB)


@pytest.mark.parametrize("raw,expected", [
    ("../../etc/passwd", "passwd"),
    ("C:\\Users\\me\\My CV (final).pdf", "My CV _final_.pdf"),
    ("<script>.pdf", "script_.pdf"),
    ("Résumé.docx", "Resume.docx"),
    ("...", "cv"),
])
def test_sanitize_filename(raw, expected):
    assert sanitize_filename(raw) == expected


def test_sanitize_filename_truncates_but_keeps_extension():
    out = sanitize_filename("a" * 300 + ".pdf")
    assert len(out) <= 120 and out.endswith(".pdf")


# --- PDF extraction --------------------------------------------------------

def test_text_pdf_extraction_preserves_sections():
    result = extract_text(f.make_text_pdf(), "pdf")
    assert result.kind == "pdf" and result.page_count == 1
    assert not result.needs_ocr and result.is_usable
    assert "PROFESSIONAL SUMMARY" in result.text
    assert "EXPERIENCE" in result.text and "EDUCATION" in result.text
    assert "\n\nEXPERIENCE" in result.text  # section boundary kept
    assert "- Led root-cause analysis" in result.text  # bullet glyph normalised


def test_image_only_pdf_flagged_for_ocr_not_treated_as_empty():
    result = extract_text(f.make_image_only_pdf(pages=2), "pdf")
    assert result.needs_ocr
    assert result.scanned_pages == (1, 2)
    assert not result.is_usable


def test_partially_scanned_pdf_warns_about_specific_pages():
    result = extract_text(f.make_mixed_pdf(), "pdf")
    assert not result.needs_ocr
    assert result.scanned_pages == (2,)
    assert any("Page(s) 2" in w for w in result.warnings)


def test_corrupt_pdf_raises_extraction_error():
    with pytest.raises(CVExtractionError, match="damaged"):
        extract_text(b"%PDF-1.4\n" + b"\x00garbage" * 100, "pdf")


def test_encrypted_pdf_raises_clear_error():
    with pytest.raises(CVExtractionError, match="password"):
        extract_text(f.make_encrypted_pdf(), "pdf")


def test_blank_pdf_without_images_raises():
    with pytest.raises(CVExtractionError, match="No text"):
        extract_text(f.make_text_pdf(lines=[]), "pdf")


def test_too_many_pages_rejected():
    with pytest.raises(CVValidationError, match="pages"):
        extract_text(f.make_text_pdf(lines=["x"], pages=31), "pdf")


def test_short_text_produces_warning():
    result = extract_text(f.make_text_pdf(lines=["Alex Example", "Engineer"]), "pdf")
    assert any("Very little text" in w for w in result.warnings)
    assert not result.is_usable


# --- DOCX extraction -------------------------------------------------------

def test_docx_extraction_includes_header_tables_and_order():
    text = extract_text(f.make_docx(), "docx").text
    assert text.startswith("alex.example@example.com")  # header contact details first
    assert "Skills | Python, SQL, SPC, FMEA" in text
    assert text.index("Professional Summary") < text.index("Experience") < text.index("Education")
    assert "- Led root-cause analysis" in text  # list paragraph marked as bullet
    assert "\n\nExperience" in text  # heading boundary kept


def test_docx_without_heading_styles_still_extracts():
    text = extract_text(f.make_docx(heading_styles=False, with_header=False), "docx").text
    assert "EXPERIENCE" in text and "EDUCATION" in text


def test_empty_docx_raises():
    with pytest.raises(CVExtractionError, match="does not contain any text"):
        extract_text(f.make_empty_docx(), "docx")


def test_corrupt_docx_raises_extraction_error():
    with pytest.raises(CVExtractionError):
        extract_text(f.make_zip_without_document(), "docx")


# --- Normalisation & session ----------------------------------------------

def test_normalize_text_collapses_whitespace_but_keeps_paragraphs():
    raw = "A\u00a0\u00a0B\r\n\r\n\r\n\r\n● item\fNext\x00"
    assert normalize_text(raw) == "A B\n\n- item\n\nNext"


def test_normalize_text_expands_ligatures():
    assert normalize_text("\ufb01nance") == "finance"


def test_process_upload_keeps_no_raw_bytes_and_sanitises_name():
    data = f.make_text_pdf()
    cv = process_upload("../My CV.pdf", data, MB)
    assert cv.filename == "My CV.pdf"
    assert cv.sha256 == fingerprint(data)
    assert not any(isinstance(v, bytes) for v in vars(cv).values())


def test_session_set_get_delete():
    state: dict = {}
    assert get_active_cv(state) is None
    cv = process_upload("cv.docx", f.make_docx(), MB)
    set_active_cv(state, cv)
    assert get_active_cv(state) is cv
    assert delete_active_cv(state) is True
    assert get_active_cv(state) is None
    assert delete_active_cv(state) is False
