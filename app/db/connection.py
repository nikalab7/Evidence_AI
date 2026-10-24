"""Create direct, TLS-required psycopg connections from local or Render settings."""

from __future__ import annotations

import psycopg

from app.config import Settings


def connect_database(*, autocommit: bool = False) -> psycopg.Connection:
    """Connect without logging a DSN; callers own the connection lifecycle."""
    database_url = Settings.load().database_url
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured")
    return psycopg.connect(
        database_url,
        connect_timeout=10,
        sslmode="require",
        autocommit=autocommit,
    )
