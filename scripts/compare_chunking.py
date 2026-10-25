"""Reproducible, local-only comparison on a synthetic development fixture."""

from __future__ import annotations

import json
import math
import re
from time import perf_counter
from typing import Any

from app.ingestion.chunkers import (
    FIXED_OVERLAP_STRATEGY,
    PARAGRAPH_STRATEGY,
    chunk_spans,
)


_SUPPORTING_SENTENCES = (
    "The settlement queue accepted signed batches only after the ledger checksum matched.",
    "A retry policy capped payment-worker attempts at four before routing to manual review.",
    "The incident review linked the queue delay to a stale signing key on the reconciliation service.",
)
_QUERIES = (
    "When did settlement batches pass ledger validation?",
    "What limit controlled worker retries before manual review?",
    "What caused the queue delay, and which service key was stale?",
)
_PARAGRAPHS = (
    "The archive records payment events with their service name and immutable sequence number. "
    + "Routine ledger context helps distinguish event order from wall-clock order. " * 3
    + _SUPPORTING_SENTENCES[0],
    "The worker reads queued batches after validating the request envelope and tenant scope. "
    + "Routine worker context describes normal retries and handoff behavior. " * 3
    + _SUPPORTING_SENTENCES[1],
    "The reconciliation service verifies signatures and refreshes its active key map on schedule. "
    + "Routine key context describes rotation and validation boundaries. " * 3
    + _SUPPORTING_SENTENCES[2],
    "The incident record links the queue, worker, and reconciliation components by timestamp. "
    + "Routine incident context keeps each service event in its own paragraph. " * 3
    + "The review retained all three source references for later audit.",
)
_TEXT = "\n\n".join(_PARAGRAPHS)


def compare(embedding_model: Any | None = None) -> dict[str, object]:
    """Measure fixture chunking and optionally rank only these synthetic passages."""
    results: dict[str, object] = {
        "fixture": "synthetic multi-source development fixture",
        "canonical_text_chars": len(_TEXT),
        "supporting_sentences": len(_SUPPORTING_SENTENCES),
        "retrieval_ranking_measured": False,
        "strategies": {},
    }
    query_vectors: list[list[float]] | None = None
    query_embedding_seconds: float | None = None
    if embedding_model is not None:
        started = perf_counter()
        query_vectors = [[float(value) for value in vector]
                         for vector in embedding_model.query_embed(list(_QUERIES))]
        query_embedding_seconds = perf_counter() - started
        if len(query_vectors) != len(_QUERIES) or any(len(vector) != 384 for vector in query_vectors):
            raise ValueError("BGE fixture queries must produce 384-dimensional embeddings")
    for strategy in (PARAGRAPH_STRATEGY, FIXED_OVERLAP_STRATEGY):
        spans = chunk_spans(_TEXT, strategy)
        chunks = [_TEXT[start:end] for start, end in spans]
        normalized_chunks = [re.sub(r"\s+", " ", chunk).strip() for chunk in chunks]
        hits = sum(
            any(sentence in chunk for chunk in normalized_chunks)
            for sentence in (re.sub(r"\s+", " ", item).strip() for item in _SUPPORTING_SENTENCES)
        )
        stored_chars = sum(end - start for start, end in spans)
        detail: dict[str, object] = {
            "chunk_count": len(spans),
            "support_sentences_found": hits,
            "support_sentence_coverage_percent": round(100 * hits / len(_SUPPORTING_SENTENCES), 2),
            "stored_chunk_chars": stored_chars,
            "overlap_or_separator_overhead_chars": stored_chars - len(_TEXT),
            "chunk_char_lengths": [end - start for start, end in spans],
        }
        if query_vectors is not None:
            started = perf_counter()
            passage_vectors = [[float(value) for value in vector]
                               for vector in embedding_model.passage_embed(chunks)]
            if len(passage_vectors) != len(chunks) or any(len(vector) != 384 for vector in passage_vectors):
                raise ValueError("BGE fixture passages must produce 384-dimensional embeddings")
            passage_embedding_seconds = perf_counter() - started
            query_ranks = []
            for query, vector in zip(_QUERIES, query_vectors):
                query_index = _QUERIES.index(query)
                query_norm = math.sqrt(sum(value * value for value in vector))
                scores = []
                for passage in passage_vectors:
                    passage_norm = math.sqrt(sum(value * value for value in passage))
                    dot = sum(left * right for left, right in zip(vector, passage))
                    scores.append(dot / (query_norm * passage_norm)
                                  if query_norm and passage_norm else 0.0)
                relevant = [index for index, chunk in enumerate(normalized_chunks)
                            if re.sub(r"\s+", " ", _SUPPORTING_SENTENCES[query_index]).strip() in chunk]
                order = sorted(range(len(scores)), key=lambda index: (-scores[index], index))
                rank = next((position + 1 for position, index in enumerate(order)
                             if index in relevant), None)
                query_ranks.append({"query": query, "first_relevant_rank": rank})
            reciprocal_ranks = [1 / row["first_relevant_rank"]
                                for row in query_ranks if row["first_relevant_rank"]]
            detail["semantic_fixture"] = {
                "recall_at_1": round(sum(row["first_relevant_rank"] == 1 for row in query_ranks)
                                      / len(query_ranks), 4),
                "mrr": round(sum(reciprocal_ranks) / len(query_ranks), 4),
                "query_ranks": query_ranks,
                "passage_embedding_seconds": round(passage_embedding_seconds, 4),
                "query_embedding_seconds_shared": round(query_embedding_seconds or 0, 4),
            }
        results["strategies"][strategy] = detail
    results["retrieval_ranking_measured"] = query_vectors is not None
    return results


if __name__ == "__main__":
    from app.embedding_smoke import MODEL_NAME
    from app.model_cache import load_model

    try:
        local_model = load_model(MODEL_NAME, threads=1)
        report = compare(local_model)
        report["embedding_model"] = MODEL_NAME
        report["model_status"] = "loaded from local cache; no network access"
    except Exception as exc:
        report = compare()
        report["embedding_model"] = MODEL_NAME
        report["model_status"] = f"unavailable ({type(exc).__name__}); ranking metrics not measured"
    print(json.dumps(report, indent=2, sort_keys=True))
