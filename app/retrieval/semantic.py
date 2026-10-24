"""Semantic retrieval using local BGE query vectors and Supabase pgvector."""

from __future__ import annotations

import math
from collections.abc import Mapping
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
) -> list[dict[str, Any]]:
    """Embed one question and return source-aware pgvector cosine results."""
    if not isinstance(query, str) or not query.strip():
        raise ValueError("search query must be a non-empty string")
    vectors = list(model.query_embed([query]))
    if len(vectors) != 1:
        raise ValueError("embedding model returned an unexpected number of query vectors")
    vector = [float(value) for value in vectors[0]]
    if len(vector) != EXPECTED_DIMENSIONS or not all(math.isfinite(value) for value in vector):
        raise ValueError("query embedding must contain 384 finite values")

    hits = semantic_search_chunks(conn, vector, limit=limit, filters=filters)
    for hit in hits:
        distance = hit["cosine_distance"]
        hit["semantic_score"] = 1.0 - distance
        hit["score"] = hit["semantic_score"]
        hit["channel"] = "semantic"
    return hits
