"""Keyword retrieval using the existing PostgreSQL English FTS index."""

from __future__ import annotations

from collections.abc import Mapping
from time import perf_counter
from typing import Any

from app.db.queries import keyword_search_chunks
from app.retrieval.keywords import DEFAULT_COMMON_TERM_THRESHOLD, KeywordStrategy


def retrieve_keyword(
    conn: Any,
    query: str,
    *,
    limit: int = 10,
    filters: Mapping[str, str] | None = None,
    timings: dict[str, float] | None = None,
    include_validation_source: bool = False,
    strategy: KeywordStrategy = "or",
    common_term_threshold: float = DEFAULT_COMMON_TERM_THRESHOLD,
) -> list[dict[str, Any]]:
    """Run English FTS with the legacy OR or informative-term strategy."""
    started = perf_counter()
    hits = keyword_search_chunks(
        conn, query, limit=limit, filters=filters,
        include_validation_source=include_validation_source,
        strategy=strategy, common_term_threshold=common_term_threshold,
    )
    if timings is not None:
        timings["keyword_sql_seconds"] = perf_counter() - started
    for hit in hits:
        hit["score"] = hit["keyword_score"]
        hit["channel"] = "keyword"
    return hits
