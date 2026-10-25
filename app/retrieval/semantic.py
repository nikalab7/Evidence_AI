"""Semantic retrieval using local BGE query vectors and Supabase pgvector."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from time import perf_counter
from typing import Any

from app.db.queries import semantic_search_chunks
from app.ingestion.corpus_core import normalize_text


EXPECTED_DIMENSIONS = 384
MAX_EXACT_TITLE_REFERENCES = 3
MAX_TITLE_FALLBACK_RESULTS = 3
_IDENTIFIER_TITLE = re.compile(r"(?<![\w])(?:[\w]+[_-]){1,}[\w]+(?![\w])", re.UNICODE)
_QUOTED_TITLE = re.compile(r"[\"“]([^\"”\r\n]{2,160})[\"”]")
_TITLECASE_PHRASE = re.compile(
    r"(?<![\w])(?:[A-Z][\w’'.-]*\s+){1,3}[A-Z][\w’'.-]*(?![\w])",
    re.UNICODE,
)
_NON_TITLE_PREFIXES = frozenset({
    "according", "can", "does", "how", "is", "tell", "the", "what", "when",
    "where", "which", "who", "why",
})


def exact_title_references(*queries: str | None) -> list[str]:
    """Extract a few high-confidence exact titles/identifiers for targeted rescue.

    Plain lower-case topic words are deliberately excluded. Title aliases are
    normalized the same way as ingestion, then matched with a bound SQL value.
    """
    references: list[str] = []
    seen: set[str] = set()
    for query in queries:
        if not isinstance(query, str):
            continue
        candidates = [match.group(0) for match in _IDENTIFIER_TITLE.finditer(query)]
        candidates.extend(match.group(1) for match in _QUOTED_TITLE.finditer(query))
        for match in _TITLECASE_PHRASE.finditer(query):
            words = match.group(0).split()
            while words and words[0].casefold() in _NON_TITLE_PREFIXES:
                words.pop(0)
            if len(words) >= 2:
                candidates.append(" ".join(words))
        for candidate in candidates:
            normalized = normalize_text(candidate)
            if normalized and normalized not in seen:
                references.append(normalized)
                seen.add(normalized)
                if len(references) >= MAX_EXACT_TITLE_REFERENCES:
                    return references
    return references


def retrieve_semantic(
    conn: Any,
    model: Any,
    query: str,
    *,
    limit: int = 10,
    filters: Mapping[str, str] | None = None,
    timings: dict[str, float] | None = None,
    include_validation_source: bool = False,
    reference_query: str | None = None,
    diagnostics: dict[str, Any] | None = None,
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

    title_references = exact_title_references(reference_query, query)
    reference_set = set(title_references)
    exact_title_already_retrieved = any(
        isinstance(source.get("title_alias"), str)
        and normalize_text(source["title_alias"]) in reference_set
        for hit in hits for source in hit.get("sources", [])
        if isinstance(source, Mapping)
    )
    fallback_needed = bool(title_references) and not exact_title_already_retrieved
    if diagnostics is not None:
        diagnostics.update({
            "semantic_title_reference_count": len(title_references),
            "semantic_title_already_retrieved": exact_title_already_retrieved,
            "semantic_title_fallback_attempted": fallback_needed,
            "semantic_title_fallback_result_count": 0,
            "semantic_title_fallback_added_count": 0,
            "semantic_title_fallback_used": False,
        })
    if not fallback_needed:
        return hits

    fallback_started = perf_counter()
    fallback_hits = semantic_search_chunks(
        conn, vector, limit=min(limit, MAX_TITLE_FALLBACK_RESULTS), filters=filters,
        include_validation_source=include_validation_source,
        exact_title_aliases=title_references,
    )
    if timings is not None:
        timings["semantic_title_fallback_sql_seconds"] = perf_counter() - fallback_started
    for hit in fallback_hits:
        distance = hit["cosine_distance"]
        hit["semantic_score"] = 1.0 - distance
        hit["score"] = hit["semantic_score"]
        hit["channel"] = "semantic"

    seen_chunk_ids = {hit["chunk_id"] for hit in fallback_hits}
    added_count = len(seen_chunk_ids - {hit["chunk_id"] for hit in hits})
    if diagnostics is not None:
        diagnostics.update({
            "semantic_title_fallback_result_count": len(fallback_hits),
            "semantic_title_fallback_added_count": added_count,
            "semantic_title_fallback_used": added_count > 0,
        })
    if not fallback_hits:
        return hits

    # An explicitly named exact title is a precise intent constraint. Put its
    # best matching chunks first, then preserve the normal semantic ordering.
    merged = list(fallback_hits)
    merged.extend(hit for hit in hits if hit["chunk_id"] not in seen_chunk_ids)
    return merged[:limit]
