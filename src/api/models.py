"""Backend API tables: accounts, sign-in tokens and each account's own CV and jobs.

These live in their own database (``settings.api_database_url``) so the single-user Streamlit
app's data is never mixed with account data. Every per-user row carries ``user_id`` and is
deleted with its account.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ApiBase(DeclarativeBase):
    pass


class User(ApiBase):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    tokens: Mapped[list[AuthToken]] = relationship(cascade="all, delete-orphan", passive_deletes=True)
    cv: Mapped[UserCV | None] = relationship(cascade="all, delete-orphan", passive_deletes=True)
    jobs: Mapped[list[UserJob]] = relationship(cascade="all, delete-orphan", passive_deletes=True)


class AuthToken(ApiBase):
    """A sign-in token. Only its SHA-256 hash is stored, never the token itself."""

    __tablename__ = "auth_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    client: Mapped[str] = mapped_column(String(40), default="web")  # e.g. "web", "extension"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserCV(ApiBase):
    """The account's current CV text. Stored only after the user consents; the file itself is never kept."""

    __tablename__ = "user_cvs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    filename: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(10))
    page_count: Mapped[int | None] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    text: Mapped[str] = mapped_column(Text)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class UserJob(ApiBase):
    """A job the user analysed (from a search, the extension or pasted text)."""

    __tablename__ = "user_jobs"
    __table_args__ = (UniqueConstraint("user_id", "job_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    job_key: Mapped[str] = mapped_column(String(600))
    title: Mapped[str] = mapped_column(String(300))
    company: Mapped[str | None] = mapped_column(String(300))
    location: Mapped[str | None] = mapped_column(String(300))
    source_name: Mapped[str] = mapped_column(String(100))
    listing_url: Mapped[str | None] = mapped_column(String(2048))
    apply_url: Mapped[str | None] = mapped_column(String(2048))
    description: Mapped[str] = mapped_column(Text)
    match_score: Mapped[float | None] = mapped_column(Float)  # snapshot from the latest analysis
    recommendation: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
