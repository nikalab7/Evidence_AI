"""Deterministic, weighted Reciprocal Rank Fusion implemented in Python."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any


def _validate_rrf_parameters(semantic_weight: float, keyword_weight: float, rrf_k: int) -> None:
    weights = (float(semantic_weight), float(keyword_weight))
    if not all(math.isfinite(weight) and weight >= 0 for weight in weights):
        raise ValueError("RRF weights must be finite, non-negative numbers")
    if sum(weights) == 0:
        raise ValueError("at least one RRF weight must be greater than zero")
    if not isinstance(rrf_k, int) or isinstance(rrf_k, bool) or rrf_k < 1:
        raise ValueError("rrf_k must be a positive integer")


def _source_key(source: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(source.get("source_id", "")),
        str(source.get("title_alias", "")),
        str(source.get("source_url", "")),
    )


def _merge_sources(target: dict[str, Any], incoming: Mapping[str, Any]) -> None:
    sources: dict[tuple[str, str, str], Mapping[str, Any]] = {
        _source_key(source): source
        for source in target.get("sources", []) if isinstance(source, Mapping)
    }
    for source in incoming.get("sources", []):
        if isinstance(source, Mapping):
            sources.setdefault(_source_key(source), source)
    target["sources"] = sorted(
        sources.values(),
        key=lambda source: (
            str(source.get("title_alias", "")).casefold(),
            str(source.get("source_id", "")),
        ),
    )


def weighted_rrf(
    semantic_hits: Sequence[Mapping[str, Any]],
    keyword_hits: Sequence[Mapping[str, Any]],
    *,
    semantic_weight: float = 1.0,
    keyword_weight: float = 1.0,
    rrf_k: int = 60,
) -> list[dict[str, Any]]:
    """Fuse ranked chunk lists, counting each chunk once per channel.

    A duplicate chunk across channels becomes one result with both channel
    ranks and scores. Duplicate rows inside one channel only use their first
    rank. Ties sort by earliest contributing rank, then stable document/chunk
    IDs so repeated runs produce the same ordering.
    """
    _validate_rrf_parameters(semantic_weight, keyword_weight, rrf_k)
    fused: dict[str, dict[str, Any]] = {}

    def add_channel(hits: Sequence[Mapping[str, Any]], channel: str, weight: float) -> None:
        if weight == 0:
            return
        seen: set[str] = set()
        for rank, hit in enumerate(hits, start=1):
            chunk_id, doc_id = hit.get("chunk_id"), hit.get("doc_id")
            if not isinstance(chunk_id, str) or not chunk_id:
                raise ValueError("every RRF result must include a stable chunk_id")
            if not isinstance(doc_id, str) or not doc_id:
                raise ValueError("every RRF result must include a stable doc_id")
            if chunk_id in seen:
                continue
            seen.add(chunk_id)

            item = fused.get(chunk_id)
            if item is None:
                item = dict(hit)
                item["score"] = 0.0
                item["channel_ranks"] = {}
                item["channel_scores"] = {}
                fused[chunk_id] = item
            elif item["doc_id"] != doc_id:
                raise ValueError("the same chunk_id cannot belong to multiple documents")
            else:
                _merge_sources(item, hit)

            score_value = hit.get("score", 0.0)
            try:
                channel_score = float(score_value)
            except (TypeError, ValueError):
                raise ValueError("retrieval scores must be numeric") from None
            if not math.isfinite(channel_score):
                raise ValueError("retrieval scores must be finite")
            item["score"] += weight / (rrf_k + rank)
            item["channel_ranks"][channel] = rank
            item["channel_scores"][channel] = channel_score

    add_channel(semantic_hits, "semantic", float(semantic_weight))
    add_channel(keyword_hits, "keyword", float(keyword_weight))
    return sorted(
        fused.values(),
        key=lambda hit: (
            -hit["score"],
            min(hit["channel_ranks"].values()),
            hit["doc_id"],
            hit["chunk_id"],
        ),
    )
