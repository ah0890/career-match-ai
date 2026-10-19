"""Encrypted file storage for original CVs and generated PDFs.

Files live in ``settings.cv_storage_dir`` under random names, encrypted with the app's key
(kept in the operating system's credential store). They are written once and never modified;
deleting the database row deletes the file.
"""

from __future__ import annotations

import secrets
from pathlib import Path

from config.settings import get_settings
from src.mail import vault


def _dir() -> Path:
    path = Path(get_settings().cv_storage_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _path(name: str) -> Path:
    if not name or "/" in name or "\\" in name or ".." in name:
        raise ValueError("Invalid stored file name.")
    return _dir() / name


def put(data: bytes) -> str:
    name = f"{secrets.token_hex(16)}.bin"
    _path(name).write_bytes(vault.encrypt_bytes(data))
    return name


def get(name: str) -> bytes:
    return vault.decrypt_bytes(_path(name).read_bytes())


def remove(name: str | None) -> None:
    if name:
        _path(name).unlink(missing_ok=True)
