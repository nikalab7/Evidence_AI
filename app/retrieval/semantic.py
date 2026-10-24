"""Semantic retrieval using local BGE query vectors and Supabase pgvector."""

from __future__ import annotations

import math
from collections.abc import Mapping
from time import perf_counter
from typing import Any

from app.db.queries import semantic_search_chunks


EXPECTED_DIMENSIONS = 384


def retrieve_semantic(
    conn: Any,
    model: Any,
    query: str,
    *,
    limit: int = 10,
    filters: Mapping[str, str] | None = None,
    timings: dict[str, float] | None = None,
    include_validation_source: bool = False,
) -> list[dict[str, Any]]:
    """Embed one question and return source-aware pgvector cosine results."""
    if not isinstance(query, str) or not query.strip():
        raise ValueError("search query must be a non-empty string")
    started = perf_counter()
    vectors = list(model.query_embed([query]))
    if timings is not None:
        timings["embedding_seconds"] = timings.get("embedding_seconds", 0.0) + perf_counter() - started
    if len(vectors) != 1:
        raise ValueError("embedding model returned an unexpected number of query vectors")
    vector = [float(value) for value in vectors[0]]
    if len(vector) != EXPECTED_DIMENSIONS or not all(math.isfinite(value) for value in vector):
        raise ValueError("query embedding must contain 384 finite values")

    started = perf_counter()
    hits = semantic_search_chunks(
        conn, vector, limit=limit, filters=filters,
        include_validation_source=include_validation_source,
    )
    if timings is not None:
        timings["semantic_sql_seconds"] = perf_counter() - started
    for hit in hits:
        distance = hit["cosine_distance"]
        hit["semantic_score"] = 1.0 - distance
        hit["score"] = hit["semantic_score"]
        hit["channel"] = "semantic"
    return hits
