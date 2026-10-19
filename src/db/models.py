"""Local database tables (SQLite by default).

CV text is stored only in ``cv_versions``, and only when the user explicitly saves a version.
Email: only messages that relate to an application keep a subject and a short snippet; unrelated
messages keep nothing but their provider id, so they are never fetched or analysed twice.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_key: Mapped[str | None] = mapped_column(String(600), unique=True)  # None for manually added jobs
    title: Mapped[str] = mapped_column(String(300))
    company: Mapped[str | None] = mapped_column(String(300))
    location: Mapped[str | None] = mapped_column(String(300))
    source_name: Mapped[str | None] = mapped_column(String(100))
    listing_url: Mapped[str | None] = mapped_column(String(2048))
    apply_url: Mapped[str | None] = mapped_column(String(2048))
    description: Mapped[str | None] = mapped_column(Text)  # the job's text, kept for later preparation
    status: Mapped[str] = mapped_column(String(30), default="Saved")
    match_score: Mapped[float | None] = mapped_column(Float)  # snapshot when saved
    recommendation: Mapped[str | None] = mapped_column(String(40))
    applied_on: Mapped[date | None] = mapped_column(Date)
    next_action: Mapped[str | None] = mapped_column(String(300))
    next_action_on: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
    # Recruitment tracking (added by migration 1)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    contact_email: Mapped[str | None] = mapped_column(String(254))  # recruiter / application address
    application_subject: Mapped[str | None] = mapped_column(String(300))  # subject of the application email
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    interview_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    interview_notes: Mapped[str | None] = mapped_column(Text)
    interviews_override: Mapped[int | None] = mapped_column(Integer)  # the user's correction of the count
    offers_override: Mapped[int | None] = mapped_column(Integer)
    status_set_manually_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    history: Mapped[list[StatusChange]] = relationship(
        back_populates="application", cascade="all, delete-orphan", order_by="StatusChange.changed_at")
    events: Mapped[list[ApplicationEvent]] = relationship(
        back_populates="application", cascade="all, delete-orphan", order_by="ApplicationEvent.occurred_at")


class StatusChange(Base):
    __tablename__ = "status_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"))
    from_status: Mapped[str | None] = mapped_column(String(30))
    to_status: Mapped[str] = mapped_column(String(30))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    application: Mapped[Application] = relationship(back_populates="history")


class ApplicationEvent(Base):
    """One dated step in an application's recruitment history (the timeline)."""

    __tablename__ = "application_events"
    __table_args__ = (Index("ix_application_events_app_time", "application_id", "occurred_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(40))  # a recruitment status or "Other Recruitment Communication"
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    summary: Mapped[str] = mapped_column(String(300))
    source: Mapped[str] = mapped_column(String(10), default="manual")  # manual / email
    message_id: Mapped[int | None] = mapped_column(ForeignKey("mail_messages.id", ondelete="SET NULL"), index=True)
    confidence: Mapped[float | None] = mapped_column(Float)  # email classifications only
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    application: Mapped[Application] = relationship(back_populates="events")
    message: Mapped[MailMessage | None] = relationship()


class MailAccount(Base):
    """A connected mailbox. The OAuth token is stored encrypted; the email password is never seen."""

    __tablename__ = "mail_accounts"
    __table_args__ = (UniqueConstraint("provider", "address"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(20))  # gmail / outlook
    address: Mapped[str] = mapped_column(String(254))
    token_ciphertext: Mapped[str] = mapped_column(Text)
    scopes: Mapped[str] = mapped_column(String(500))
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # last successful sync
    sync_status: Mapped[str] = mapped_column(String(20), default="never")  # never / ok / error / reconnect
    last_error: Mapped[str | None] = mapped_column(String(300))

    messages: Mapped[list[MailMessage]] = relationship(cascade="all, delete-orphan", passive_deletes=True)
    runs: Mapped[list[SyncRun]] = relationship(cascade="all, delete-orphan", passive_deletes=True)


class MailMessage(Base):
    """An email seen during sync. Unrelated messages keep only their provider id."""

    __tablename__ = "mail_messages"
    __table_args__ = (
        UniqueConstraint("account_id", "provider_id"),
        Index("ix_mail_messages_thread", "account_id", "thread_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("mail_accounts.id", ondelete="CASCADE"))
    provider_id: Mapped[str] = mapped_column(String(200))
    thread_id: Mapped[str | None] = mapped_column(String(200))
    internet_id: Mapped[str | None] = mapped_column(String(300), index=True)  # RFC 5322 Message-ID
    direction: Mapped[str] = mapped_column(String(3))  # in / out
    relevance: Mapped[str] = mapped_column(String(15))  # matched / review / unrelated / dismissed
    from_address: Mapped[str | None] = mapped_column(String(254))
    from_name: Mapped[str | None] = mapped_column(String(200))
    to_addresses: Mapped[str | None] = mapped_column(String(1000))
    subject: Mapped[str | None] = mapped_column(String(300))
    snippet: Mapped[str | None] = mapped_column(String(400))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    web_link: Mapped[str | None] = mapped_column(String(2048))
    application_id: Mapped[int | None] = mapped_column(ForeignKey("applications.id", ondelete="SET NULL"),
                                                       index=True)
    kind: Mapped[str | None] = mapped_column(String(40))  # classification
    confidence: Mapped[float | None] = mapped_column(Float)  # classification confidence
    match_confidence: Mapped[float | None] = mapped_column(Float)
    reason: Mapped[str | None] = mapped_column(String(300))  # why it was matched or flagged
    user_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)  # never changed by a later sync
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class SyncRun(Base):
    """One synchronisation attempt, kept for the sync log."""

    __tablename__ = "sync_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("mail_accounts.id", ondelete="CASCADE"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="running")  # running / ok / error / reconnect
    trigger: Mapped[str] = mapped_column(String(20), default="manual")  # manual / auto / cli
    fetched: Mapped[int] = mapped_column(Integer, default=0)
    new: Mapped[int] = mapped_column(Integer, default=0)
    matched: Mapped[int] = mapped_column(Integer, default=0)
    review: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(String(300))


class SchemaMigration(Base):
    __tablename__ = "schema_migrations"

    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class StudyProgress(Base):
    __tablename__ = "study_progress"
    __table_args__ = (UniqueConstraint("job_key", "topic_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_key: Mapped[str] = mapped_column(String(600))
    topic_id: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(30))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class HttpCacheEntry(Base):
    """A cached job-source response, so restarts do not repeat requests the source asked us to limit."""

    __tablename__ = "http_cache"

    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    provider_id: Mapped[str] = mapped_column(String(50), index=True)
    payload: Mapped[str] = mapped_column(Text)  # JSON
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RequestCount(Base):
    """Live requests made to a source per calendar day, kept across restarts."""

    __tablename__ = "request_counts"

    provider_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)


class SearchHistory(Base):
    __tablename__ = "search_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    keywords: Mapped[str] = mapped_column(String(200))
    query_json: Mapped[str] = mapped_column(Text)  # the full SearchQuery, to search again
    summary: Mapped[str] = mapped_column(String(300))  # e.g. "Quality Engineer · Germany · Remote"
    total_jobs: Mapped[int] = mapped_column(Integer, default=0)
    sources_ok: Mapped[int] = mapped_column(Integer, default=0)
    sources_failed: Mapped[int] = mapped_column(Integer, default=0)
    searched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class CVVersion(Base):
    """A CV the user chose to keep. Only extracted text is stored, never the original file."""

    __tablename__ = "cv_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    purpose: Mapped[str | None] = mapped_column(String(300))  # e.g. "Quality management roles"
    filename: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(10))  # pdf / docx
    page_count: Mapped[int | None] = mapped_column(Integer)
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    text: Mapped[str] = mapped_column(Text)
    ats_score: Mapped[int | None] = mapped_column(Integer)  # snapshot when saved
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
