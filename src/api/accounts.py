"""Accounts: password hashing, sign-in with lockout, and opaque bearer tokens.

Passwords are hashed with scrypt (standard library) and a per-user salt. Tokens are random
256-bit values; the database keeps only their SHA-256 hash, so a leaked database cannot be
used to sign in.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from src.api.models import AuthToken, User

_SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")
MIN_PASSWORD, MAX_PASSWORD = 10, 128


class AccountError(ValueError):
    """A user-safe message about why an account action failed."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)  # SQLite returns naive datetimes


def normalise_email(email: str) -> str:
    value = email.strip().lower()
    if len(value) > 254 or not _EMAIL.match(value):
        raise AccountError("Enter a valid email address.")
    return value


def check_password_policy(password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise AccountError(f"Use a password of at least {MIN_PASSWORD} characters.")
    if len(password) > MAX_PASSWORD:
        raise AccountError(f"Use a password of at most {MAX_PASSWORD} characters.")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return f"scrypt${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_b64, digest_b64 = stored.split("$")
        salt, expected = base64.b64decode(salt_b64), base64.b64decode(digest_b64)
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    actual = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return hmac.compare_digest(actual, expected)


# Verified against when the email is unknown, so response time does not reveal which emails exist.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def register(session: Session, email: str, password: str) -> User:
    email = normalise_email(email)
    check_password_policy(password)
    if session.scalar(select(User).where(User.email == email)) is not None:
        raise AccountError("An account with this email already exists. Sign in instead.")
    user = User(email=email, password_hash=hash_password(password))
    session.add(user)
    session.flush()
    return user


def authenticate(session: Session, email: str, password: str, max_failed: int, lockout_minutes: int) -> User:
    """Return the user, or raise a deliberately vague error. Repeated failures lock the account briefly."""
    generic = AccountError("Email or password is incorrect.")
    try:
        email = normalise_email(email)
    except AccountError:
        raise generic from None
    user = session.scalar(select(User).where(User.email == email))
    if user is None:
        verify_password(password, _DUMMY_HASH)
        raise generic
    now = _utcnow()
    if user.locked_until and _aware(user.locked_until) > now:
        raise AccountError("Too many failed sign-in attempts. Try again in a few minutes.")
    if not verify_password(password, user.password_hash):
        user.failed_logins += 1
        if user.failed_logins >= max_failed:
            user.failed_logins = 0
            user.locked_until = now + timedelta(minutes=lockout_minutes)
        raise generic
    user.failed_logins = 0
    user.locked_until = None
    return user


def issue_token(session: Session, user: User, days: int, client: str = "web") -> str:
    token = secrets.token_urlsafe(32)
    session.add(AuthToken(user_id=user.id, token_hash=token_hash(token), client=client[:40],
                          expires_at=_utcnow() + timedelta(days=days)))
    session.flush()
    return token


def resolve_token(session: Session, token: str) -> User | None:
    if not token or len(token) > 200:
        return None
    row = session.scalar(select(AuthToken).where(AuthToken.token_hash == token_hash(token)))
    now = _utcnow()
    if row is None:
        return None
    if _aware(row.expires_at) <= now:
        session.delete(row)
        return None
    row.last_used_at = now
    return session.get(User, row.user_id)


def revoke_token(session: Session, token: str) -> None:
    session.execute(delete(AuthToken).where(AuthToken.token_hash == token_hash(token)))


def delete_account(session: Session, user: User) -> None:
    session.delete(user)
