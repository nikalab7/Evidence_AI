"""Ingest an explicitly selected prefix of the audited HotpotQA corpus."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import statistics
import sys
import time
from typing import Any

import psycopg

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.db.connection import connect_database
from app.db.queries import (
    apply_schema,
    cosine_search,
    insert_batch,
    read_database_document_ids,
    read_database_metrics,
    verify_target_documents,
)
from app.embedding_smoke import MODEL_NAME
from app.ingestion.indexer import embed_documents, prepare_document
from app.model_cache import load_model


CORPUS_PATH = PROJECT_ROOT / "data" / "corpus.jsonl"
SCHEMA_PATH = PROJECT_ROOT / "migrations" / "schema.sql"
MAX_DOCUMENTS = 1_000
DEFAULT_DOCUMENT_LIMIT = 100
DEFAULT_BATCH_SIZE = 25
EXPECTED_DIMENSIONS = 384
COSINE_BENCHMARK_QUERY = "What events led to a change in policy, and which organizations were affected?"
COSINE_BENCHMARK_WARMUPS = 2
COSINE_BENCHMARK_RUNS = 10


def validate_document_limit(limit: int) -> int:
    """Reject non-positive limits and enforce the hard 1,000-document ceiling."""
    if not 1 <= limit <= MAX_DOCUMENTS:
        raise ValueError(f"document limit must be between 1 and {MAX_DOCUMENTS}")
    return limit


def validate_database_document_scope(
    existing_ids: set[str], target_ids: set[str],
) -> int:
    """Ensure the selected corpus prefix cannot push the database over the cap."""
    if len(target_ids) > MAX_DOCUMENTS:
        raise ValueError("selected corpus prefix exceeds the 1,000-document milestone limit")
    if existing_ids - target_ids:
        raise ValueError("database contains documents outside the selected corpus prefix; refusing writes")
    final_count = len(existing_ids | target_ids)
    if final_count > MAX_DOCUMENTS:
        raise ValueError("ingestion would exceed the 1,000-document milestone limit")
    return final_count


def load_first_unique_documents(
    path: Path, target: int = DEFAULT_DOCUMENT_LIMIT,
) -> tuple[list[dict[str, Any]], int]:
    """Read exactly ``target`` unique, validated content-addressed corpus rows."""
    validate_document_limit(target)
    documents: list[dict[str, Any]] = []
    seen: set[str] = set()
    records_read = 0
    with path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            records_read += 1
            try:
                document = prepare_document(json.loads(line))
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                raise ValueError(
                    f"invalid corpus record at line {line_number}: {type(exc).__name__}"
                ) from None
            if document["doc_id"] in seen:
                continue
            seen.add(document["doc_id"])
            documents.append(document)
            if len(documents) == target:
                return documents, records_read
    raise ValueError(f"corpus ended after {len(documents)} unique documents; {target} are required")


def _query_embedding(model: Any) -> list[float]:
    vectors = list(model.query_embed([COSINE_BENCHMARK_QUERY]))
    if len(vectors) != 1:
        raise RuntimeError("query embedding model returned an unexpected number of vectors")
    vector = [float(value) for value in vectors[0]]
    if len(vector) != EXPECTED_DIMENSIONS or not all(math.isfinite(value) for value in vector):
        raise RuntimeError("cosine benchmark query embedding must contain 384 finite values")
    return vector


def benchmark_cosine_search(
    conn: Any, vector: list[float], *, warmups: int = COSINE_BENCHMARK_WARMUPS,
    runs: int = COSINE_BENCHMARK_RUNS,
) -> dict[str, Any]:
    """Time repeated real pgvector SQL searches using an independent text query."""
    for _ in range(warmups):
        cosine_search(conn, vector, limit=5)

    elapsed_ms: list[float] = []
    ranked_results: list[dict[str, Any]] = []
    for _ in range(runs):
        started = time.perf_counter()
        results = cosine_search(conn, vector, limit=5)
        elapsed_ms.append((time.perf_counter() - started) * 1000)
        distances = [item["cosine_distance"] for item in results]
        if not results or distances != sorted(distances):
            raise RuntimeError("cosine-distance SQL did not return ranked results")
        ranked_results = results

    ordered = sorted(elapsed_ms)
    p95_index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return {
        "query_text": COSINE_BENCHMARK_QUERY,
        "query_source": "independent natural-language query; not a stored chunk vector",
        "warmup_runs": warmups,
        "measured_runs": runs,
        "latency_ms": {
            "minimum": round(ordered[0], 3),
            "median": round(statistics.median(ordered), 3),
            "p95_nearest_rank": round(ordered[p95_index], 3),
            "maximum": round(ordered[-1], 3),
        },
        "ranked_results": ranked_results,
        "distance_ordered": True,
        "retrieval_quality_evaluated": False,
    }


def run_ingestion(
    document_limit: int = DEFAULT_DOCUMENT_LIMIT,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> dict[str, Any]:
    """Embed locally, write bounded parameterized batches, and verify persistence."""
    validate_document_limit(document_limit)
    if not 1 <= batch_size <= MAX_DOCUMENTS:
        raise ValueError(f"batch size must be between 1 and {MAX_DOCUMENTS}")
    total_started = time.perf_counter()

    phase_started = time.perf_counter()
    documents, records_read = load_first_unique_documents(CORPUS_PATH, document_limit)
    corpus_seconds = time.perf_counter() - phase_started
    doc_ids = [document["doc_id"] for document in documents]
    target_ids = set(doc_ids)
    expected_sources = sum(len(document["sources"]) for document in documents)
    expected_chunks = sum(len(document["chunks"]) for document in documents)

    phase_started = time.perf_counter()
    model = load_model(MODEL_NAME)
    model_initialization_seconds = time.perf_counter() - phase_started
    phase_started = time.perf_counter()
    embed_documents(documents, model, MODEL_NAME, batch_size=batch_size)
    embedding_seconds = time.perf_counter() - phase_started
    chunks_embedded = sum(len(document["chunks"]) for document in documents)
    phase_started = time.perf_counter()
    query_vector = _query_embedding(model)
    query_embedding_seconds = time.perf_counter() - phase_started

    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    inserted = {"documents_inserted": 0, "sources_inserted": 0, "chunks_inserted": 0}
    database_started = time.perf_counter()
    with connect_database(autocommit=True) as conn:
        conn.execute("SET statement_timeout = '30000'")
        before = read_database_metrics(conn)
        with conn.transaction():
            apply_schema(conn, schema_sql)
        existing_ids = read_database_document_ids(conn)
        expected_total_documents = validate_database_document_scope(existing_ids, target_ids)

        for start in range(0, len(documents), batch_size):
            with conn.transaction():
                batch_result = insert_batch(conn, documents[start:start + batch_size])
            for key, value in batch_result.items():
                inserted[key] += value

        after = read_database_metrics(conn)
        state = verify_target_documents(conn, doc_ids)
        search = benchmark_cosine_search(conn, query_vector)

    database_seconds = time.perf_counter() - database_started
    if state["target_documents"] != document_limit:
        raise RuntimeError("database does not contain every requested target document")
    if state["total_documents"] != expected_total_documents:
        raise RuntimeError("database total document count changed outside the selected corpus prefix")
    if state["target_sources"] != expected_sources or state["target_chunks"] != expected_chunks:
        raise RuntimeError("database provenance or chunk counts do not match the selected corpus")
    if (state["orphan_target_chunks"] or state["orphan_target_sources"]
            or state["wrong_dimension_target_embeddings"]):
        raise RuntimeError("database contains orphan rows or embeddings with dimensions other than 384")

    with connect_database(autocommit=True) as fresh_conn:
        fresh_conn.execute("SET statement_timeout = '30000'")
        fresh_state = verify_target_documents(fresh_conn, doc_ids)
    if (fresh_state["target_documents"] != document_limit
            or fresh_state["target_sources"] != expected_sources
            or fresh_state["target_chunks"] != expected_chunks
            or fresh_state["total_documents"] != expected_total_documents
            or fresh_state["orphan_target_chunks"] or fresh_state["orphan_target_sources"]
            or fresh_state["wrong_dimension_target_embeddings"]):
        raise RuntimeError("fresh database connection could not verify inserted rows")

    total_seconds = time.perf_counter() - total_started
    return {
        "status": "passed",
        "documents_requested": document_limit,
        "unique_documents_read": len(documents),
        "corpus_records_read": records_read,
        "embedding_model": MODEL_NAME,
        "embedding_dimensions": EXPECTED_DIMENSIONS,
        "chunking_strategy": "paragraph",
        "batch_size": batch_size,
        "inserted": inserted,
        "existing_documents_before": len(existing_ids),
        "expected_total_documents_after": expected_total_documents,
        "chunks_embedded": chunks_embedded,
        "timings_seconds": {
            "corpus_read": round(corpus_seconds, 3),
            "model_initialization": round(model_initialization_seconds, 3),
            "embedding_generation": round(embedding_seconds, 3),
            "query_embedding": round(query_embedding_seconds, 3),
            "database_write_and_verification": round(database_seconds, 3),
            "total": round(total_seconds, 3),
        },
        "throughput": {
            "embedded_chunks_per_second": round(chunks_embedded / embedding_seconds, 3)
            if embedding_seconds else None,
            "inserted_documents_per_database_second": round(
                inserted["documents_inserted"] / database_seconds, 3,
            ) if database_seconds else None,
            "inserted_documents_per_total_second": round(
                inserted["documents_inserted"] / total_seconds, 3,
            ) if total_seconds else None,
        },
        "database_before": before,
        "database_after": after,
        "verified_state": state,
        "fresh_connection_read_passed": True,
        "cosine_search_benchmark": search,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit", type=int, default=DEFAULT_DOCUMENT_LIMIT,
        help=f"unique corpus documents to ensure in Supabase (maximum {MAX_DOCUMENTS})",
    )
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    args = parser.parse_args()
    try:
        report = run_ingestion(document_limit=args.limit, batch_size=args.batch_size)
    except psycopg.Error as exc:
        print(json.dumps({
            "status": "failed", "error": "database_error",
            "error_type": type(exc).__name__, "sqlstate": exc.sqlstate,
        }), file=sys.stderr)
        return 1
    except (OSError, ValueError, RuntimeError) as exc:
        print(json.dumps({
            "status": "failed", "error_type": type(exc).__name__, "message": str(exc),
        }), file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
