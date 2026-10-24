"""Create direct, TLS-required psycopg connections from local or Render settings."""

from __future__ import annotations

import re
from urllib.parse import unquote, urlsplit

import psycopg

from app.config import Settings


EXPECTED_SUPABASE_PROJECT_REF = "csenhlrsttuukzwglttf"
_PROJECT_REF_RE = re.compile(r"^[a-z0-9]{20}$")


def project_ref_from_database_url(database_url: str) -> str | None:
    """Extract a project ref only from standard Supabase direct/pooler URLs."""
    try:
        parsed = urlsplit(database_url)
        hostname = (parsed.hostname or "").lower()
        if hostname.endswith(".supabase.co") and hostname.startswith("db."):
            candidate = hostname[3:-len(".supabase.co")]
            return candidate if _PROJECT_REF_RE.fullmatch(candidate) else None
        if hostname.endswith(".pooler.supabase.com"):
            username = unquote(parsed.username or "")
            candidate = username.rsplit(".", 1)[-1]
            return candidate if _PROJECT_REF_RE.fullmatch(candidate) else None
    except (TypeError, ValueError):
        return None
    return None


def connect_database(*, autocommit: bool = False) -> psycopg.Connection:
    """Connect only to the approved project without logging the DSN."""
    database_url = Settings.load().database_url
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured")
    project_ref = project_ref_from_database_url(database_url)
    if project_ref != EXPECTED_SUPABASE_PROJECT_REF:
        raise RuntimeError(
            "DATABASE_URL project identity is unknown or not the approved Evidence_AI project; refusing connection"
        )
    return psycopg.connect(
        database_url,
        connect_timeout=10,
        sslmode="require",
        autocommit=autocommit,
    )
