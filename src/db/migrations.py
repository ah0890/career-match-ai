"""Small, ordered schema migrations for databases created by earlier versions.

``create_all`` creates missing *tables*, but never adds columns to an existing table or changes
stored values. Each migration below runs once, inside a transaction, and is recorded in
``schema_migrations``. A fresh database already has every column, so the column steps are no-ops.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy import Connection, Engine, inspect, text

# Statuses before recruitment tracking → their equivalent now.
LEGACY_STATUSES = {"Applied": "Application Submitted", "Interview": "Interview Scheduled", "Offer": "Offer Received"}

_APPLICATION_COLUMNS = {
    "applied_at": "DATETIME",
    "contact_email": "VARCHAR(254)",
    "application_subject": "VARCHAR(300)",
    "last_activity_at": "DATETIME",
    "interview_at": "DATETIME",
    "interview_notes": "TEXT",
    "interviews_override": "INTEGER",
    "offers_override": "INTEGER",
    "status_set_manually_at": "DATETIME",
}


def _add_columns(conn: Connection, table: str, columns: dict[str, str]) -> None:
    existing = {c["name"] for c in inspect(conn).get_columns(table)}
    for name, ddl in columns.items():
        if name not in existing:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))  # names are constants above


def _m1_recruitment_tracking(conn: Connection) -> None:
    _add_columns(conn, "applications", _APPLICATION_COLUMNS)
    for old, new in LEGACY_STATUSES.items():
        conn.execute(text("UPDATE applications SET status = :new WHERE status = :old"), {"old": old, "new": new})
        conn.execute(text("UPDATE status_changes SET to_status = :new WHERE to_status = :old"), {"old": old, "new": new})
        conn.execute(text("UPDATE status_changes SET from_status = :new WHERE from_status = :old"),
                     {"old": old, "new": new})
    # The timeline starts from the existing status history.
    conn.execute(text(
        "INSERT INTO application_events (application_id, kind, occurred_at, summary, source, created_at) "
        "SELECT application_id, to_status, changed_at, 'Status set to ' || to_status, 'manual', changed_at "
        "FROM status_changes"))
    conn.execute(text(
        "UPDATE applications SET last_activity_at = "
        "(SELECT MAX(changed_at) FROM status_changes WHERE status_changes.application_id = applications.id) "
        "WHERE last_activity_at IS NULL"))


def _m2_cv_workspace(conn: Connection) -> None:
    _add_columns(conn, "applications", {"cv_doc_id": "INTEGER", "cv_revision_number": "INTEGER"})


def _m3_cv_exports(conn: Connection) -> None:
    _add_columns(conn, "cv_files", {"kind": "VARCHAR(5) NOT NULL DEFAULT 'pdf'", "application_id": "INTEGER"})


MIGRATIONS: tuple[tuple[int, str, Callable[[Connection], None]], ...] = (
    (1, "recruitment tracking", _m1_recruitment_tracking),
    (2, "cv workspace", _m2_cv_workspace),
    (3, "cv exports", _m3_cv_exports),
)


def migrate(engine: Engine) -> list[int]:
    """Apply pending migrations; returns the versions applied."""
    applied: list[int] = []
    with engine.begin() as conn:
        done = {row[0] for row in conn.execute(text("SELECT version FROM schema_migrations"))}
    for version, name, step in MIGRATIONS:
        if version in done:
            continue
        with engine.begin() as conn:
            step(conn)
            conn.execute(text("INSERT INTO schema_migrations (version, name, applied_at) VALUES (:v, :n, :t)"),
                         {"v": version, "n": name,
                          "t": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")})  # SQLAlchemy's format
        applied.append(version)
    return applied
