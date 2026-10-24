"""Keyword retrieval using the existing PostgreSQL English FTS index."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.db.queries import keyword_search_chunks


def retrieve_keyword(
    conn: Any,
    query: str,
    *,
    limit: int = 10,
    filters: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Run websearch_to_tsquery against indexed chunk text and return ranked hits."""
    hits = keyword_search_chunks(conn, query, limit=limit, filters=filters)
    for hit in hits:
        hit["score"] = hit["keyword_score"]
        hit["channel"] = "keyword"
    return hits
