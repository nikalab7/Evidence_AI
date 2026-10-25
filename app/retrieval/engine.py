"""One small interface for semantic, keyword, and hybrid search."""

from __future__ import annotations

from collections.abc import Mapping
from time import perf_counter
from typing import Any, Literal

from app.retrieval.keyword import retrieve_keyword
from app.retrieval.keywords import DEFAULT_COMMON_TERM_THRESHOLD, KeywordStrategy
from app.retrieval.ranker import weighted_rrf
from app.retrieval.semantic import retrieve_semantic


RetrievalMode = Literal["semantic", "keyword", "hybrid"]
DEFAULT_EXCERPT_CHARACTERS = 500


def _present_hit(
    hit: dict[str, Any], rank: int, method: str, *,
    include_evidence_text: bool = False,
    include_validation_source: bool = False,
) -> dict[str, Any]:
    result = dict(hit)
    text = result.pop("chunk_text", "")
    validation_source = result.pop("validation_source", None)
    sources = hit.get("sources") or []
    metadata = hit.get("metadata") or {}
    titles = sorted(
        {source["title_alias"] for source in sources if source.get("title_alias")},
        key=lambda title: (title.casefold(), title),
    )
    excerpt = text[:DEFAULT_EXCERPT_CHARACTERS]
    if len(text) > DEFAULT_EXCERPT_CHARACTERS:
        excerpt = excerpt.rstrip() + "…"
    presented = {
        **result,
        "metadata": {
            key: value for key, value in metadata.items()
            if key not in {"source_variants", "title", "doc_id", "content_hash"}
        },
        "rank": rank,
        "retrieval_method": method,
        "channel": method,
        "title": titles[0] if titles else None,
        "titles": titles,
        "text_excerpt": excerpt,
    }
    if include_evidence_text:
        presented["evidence_text"] = text
    if include_validation_source and validation_source is not None:
        presented["validation_source"] = validation_source
    return presented


def search(
    conn: Any,
    query: str,
    *,
    mode: RetrievalMode = "hybrid",
    limit: int = 10,
    candidate_limit: int = 20,
    model: Any | None = None,
    filters: Mapping[str, str] | None = None,
    semantic_weight: float = 1.0,
    keyword_weight: float = 1.0,
    rrf_k: int = 60,
    timings: dict[str, float] | None = None,
    include_evidence_text: bool = False,
    include_validation_source: bool = False,
    keyword_strategy: KeywordStrategy = "or",
    common_term_threshold: float = DEFAULT_COMMON_TERM_THRESHOLD,
    semantic_reference_query: str | None = None,
    diagnostics: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Retrieve stable, provenance-aware chunk results with one ranked API."""
    if mode not in ("semantic", "keyword", "hybrid"):
        raise ValueError(f"unsupported retrieval mode: {mode}")
    if not isinstance(query, str):
        raise ValueError("search query must be a string")
    if not query.strip():
        if mode == "keyword":
            return []
        raise ValueError("search query must be a non-empty string")
    if not 1 <= limit <= 100:
        raise ValueError("result limit must be between 1 and 100")
    if not limit <= candidate_limit <= 100:
        raise ValueError("candidate limit must be at least the result limit and at most 100")
    if mode == "hybrid":
        weighted_rrf(
            [], [], semantic_weight=semantic_weight,
            keyword_weight=keyword_weight, rrf_k=rrf_k,
        )

    retrieval_started = perf_counter()
    if mode == "semantic":
        if model is None:
            raise ValueError("semantic retrieval requires an embedding model")
        hits = retrieve_semantic(
            conn, model, query, limit=limit, filters=filters, timings=timings,
            include_validation_source=include_validation_source,
            reference_query=semantic_reference_query, diagnostics=diagnostics,
        )
        if timings is not None:
            timings["retrieval_processing_seconds"] = perf_counter() - retrieval_started
        return [_present_hit(hit, rank, mode, include_evidence_text=include_evidence_text,
                             include_validation_source=include_validation_source)
                for rank, hit in enumerate(hits, start=1)]

    if mode == "keyword":
        hits = retrieve_keyword(
            conn, query, limit=limit, filters=filters, timings=timings,
            include_validation_source=include_validation_source,
            strategy=keyword_strategy,
            common_term_threshold=common_term_threshold,
        )
        if timings is not None:
            timings["retrieval_processing_seconds"] = perf_counter() - retrieval_started
        return [_present_hit(hit, rank, mode, include_evidence_text=include_evidence_text,
                             include_validation_source=include_validation_source)
                for rank, hit in enumerate(hits, start=1)]

    if model is None:
        raise ValueError("hybrid retrieval requires an embedding model")
    semantic_hits = retrieve_semantic(
        conn, model, query, limit=candidate_limit, filters=filters, timings=timings,
        include_validation_source=include_validation_source,
        reference_query=semantic_reference_query, diagnostics=diagnostics,
    )
    keyword_hits = retrieve_keyword(
        conn, query, limit=candidate_limit, filters=filters, timings=timings,
        include_validation_source=include_validation_source,
        strategy=keyword_strategy,
        common_term_threshold=common_term_threshold,
    )
    fusion_started = perf_counter()
    hits = weighted_rrf(
        semantic_hits,
        keyword_hits,
        semantic_weight=semantic_weight,
        keyword_weight=keyword_weight,
        rrf_k=rrf_k,
    )
    if timings is not None:
        timings["fusion_seconds"] = perf_counter() - fusion_started
        timings["retrieval_processing_seconds"] = perf_counter() - retrieval_started
    return [_present_hit(hit, rank, "hybrid", include_evidence_text=include_evidence_text,
                         include_validation_source=include_validation_source)
            for rank, hit in enumerate(hits[:limit], start=1)]
