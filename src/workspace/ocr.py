"""Optional OCR for scanned PDFs, using Tesseract through PyMuPDF when it is installed.

Tesseract is a free program, not a Python package. Without it the app says so and asks for a
text-based PDF or DOCX instead — it never pretends to have read a scanned page.
"""

from __future__ import annotations

OCR_HELP = ("Text recognition needs the free Tesseract program. On Windows, install it from "
            "https://github.com/UB-Mannheim/tesseract/wiki (keep “English” selected), then restart CareerMatch. "
            "Or export your CV from Word or Google Docs as a text-based PDF or DOCX.")


class OCRUnavailable(RuntimeError):
    pass


def available() -> bool:
    try:
        import pymupdf
        pymupdf.get_tessdata()
        return True
    except Exception:
        return False


def ocr_pdf(data: bytes, max_pages: int = 5, language: str = "eng") -> str:
    """Recognised text of the first pages, in reading order. Raises OCRUnavailable without Tesseract."""
    import pymupdf
    try:
        tessdata = pymupdf.get_tessdata()
    except Exception as exc:
        raise OCRUnavailable(OCR_HELP) from exc
    parts = []
    with pymupdf.open(stream=data, filetype="pdf") as pdf:
        for page in list(pdf)[:max_pages]:
            textpage = page.get_textpage_ocr(language=language, dpi=300, full=True, tessdata=tessdata)
            parts.append(page.get_text("text", textpage=textpage))
    return "\n".join(parts).strip()
