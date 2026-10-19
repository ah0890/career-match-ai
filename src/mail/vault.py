"""Encrypted storage for email OAuth tokens.

Tokens are encrypted with Fernet (AES-128-CBC + HMAC-SHA256). The key lives in the operating
system's credential store (Windows Credential Manager, macOS Keychain, Secret Service), never in
the database — so a copied database file is useless without the user's own login. Only if no
credential store exists is the key kept in a local file, and the app says so.
"""

from __future__ import annotations

import json
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from config.settings import DATA_DIR

SERVICE = "CareerMatch AI"
KEY_NAME = "mail-token-key"
KEY_FILE = DATA_DIR / ".mail_token_key"


class VaultError(RuntimeError):
    """The stored token cannot be read (e.g. the key was removed): the account must be reconnected."""


def _keyring_get() -> str | None:
    try:
        import keyring
        return keyring.get_password(SERVICE, KEY_NAME)
    except Exception:  # no usable backend
        return None


def _keyring_set(value: str) -> bool:
    try:
        import keyring
        keyring.set_password(SERVICE, KEY_NAME, value)
        return keyring.get_password(SERVICE, KEY_NAME) == value
    except Exception:
        return False


def key_location() -> str:
    """Where the key is kept, for the privacy notice."""
    return "your system's credential store" if _keyring_get() else f"the file {KEY_FILE.name} in the data folder"


def _load_key() -> bytes:
    if stored := _keyring_get():
        return stored.encode()
    if KEY_FILE.exists():
        return KEY_FILE.read_bytes().strip()
    key = Fernet.generate_key()
    if not _keyring_set(key.decode()):
        Path(KEY_FILE).parent.mkdir(parents=True, exist_ok=True)
        KEY_FILE.write_bytes(key)
    return key


def encrypt(token: dict) -> str:
    return Fernet(_load_key()).encrypt(json.dumps(token).encode()).decode()


def decrypt(ciphertext: str) -> dict:
    try:
        return json.loads(Fernet(_load_key()).decrypt(ciphertext.encode()))
    except (InvalidToken, ValueError) as exc:
        raise VaultError("The saved sign-in for this mailbox can no longer be read. Reconnect it.") from exc
