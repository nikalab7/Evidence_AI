"""One small interface for semantic, keyword, and hybrid search."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from app.retrieval.keyword import retrieve_keyword
from app.retrieval.ranker import weighted_rrf
from app.retrieval.semantic import retrieve_semantic


RetrievalMode = Literal["semantic", "keyword", "hybrid"]
DEFAULT_EXCERPT_CHARACTERS = 500


def _present_hit(hit: dict[str, Any], rank: int, method: str) -> dict[str, Any]:
    result = dict(hit)
    text = result.pop("chunk_text", "")
    sources = hit.get("sources") or []
    metadata = hit.get("metadata") or {}
    titles = sorted(
        {source["title_alias"] for source in sources if source.get("title_alias")},
        key=lambda title: (title.casefold(), title),
    )
    excerpt = text[:DEFAULT_EXCERPT_CHARACTERS]
    if len(text) > DEFAULT_EXCERPT_CHARACTERS:
        excerpt = excerpt.rstrip() + "…"
    return {
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

    if mode == "semantic":
        if model is None:
            raise ValueError("semantic retrieval requires an embedding model")
        hits = retrieve_semantic(conn, model, query, limit=limit, filters=filters)
        return [_present_hit(hit, rank, mode) for rank, hit in enumerate(hits, start=1)]

    if mode == "keyword":
        hits = retrieve_keyword(conn, query, limit=limit, filters=filters)
        return [_present_hit(hit, rank, mode) for rank, hit in enumerate(hits, start=1)]

    if model is None:
        raise ValueError("hybrid retrieval requires an embedding model")
    semantic_hits = retrieve_semantic(
        conn, model, query, limit=candidate_limit, filters=filters,
    )
    keyword_hits = retrieve_keyword(conn, query, limit=candidate_limit, filters=filters)
    hits = weighted_rrf(
        semantic_hits,
        keyword_hits,
        semantic_weight=semantic_weight,
        keyword_weight=keyword_weight,
        rrf_k=rrf_k,
    )
    return [_present_hit(hit, rank, "hybrid") for rank, hit in enumerate(hits[:limit], start=1)]
