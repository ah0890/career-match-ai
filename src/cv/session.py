"""The active CV for the current browser session.

Only extracted text and metadata are held — never the original file bytes — and
only in this session's memory. Deleting the CV removes it immediately.
"""

from __future__ import annotations

from collections.abc import MutableMapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from src.cv.extraction import ExtractionResult, extract_text, fingerprint, sanitize_filename, validate_upload

_KEY = "cm_active_cv"


@dataclass(frozen=True)
class ActiveCV:
    filename: str
    size_bytes: int
    sha256: str
    uploaded_at: datetime
    extraction: ExtractionResult


def process_upload(filename: str, data: bytes, max_bytes: int) -> ActiveCV:
    """Validate and extract a CV. Raises CVError subclasses with user-safe messages."""
    kind = validate_upload(filename, data, max_bytes)
    extraction = extract_text(data, kind)
    return ActiveCV(
        filename=sanitize_filename(filename),
        size_bytes=len(data),
        sha256=fingerprint(data),
        uploaded_at=datetime.now(timezone.utc),
        extraction=extraction,
    )


def get_active_cv(state: MutableMapping[str, Any]) -> ActiveCV | None:
    return state.get(_KEY)


def set_active_cv(state: MutableMapping[str, Any], cv: ActiveCV) -> None:
    state[_KEY] = cv


def delete_active_cv(state: MutableMapping[str, Any]) -> bool:
    return state.pop(_KEY, None) is not None
