"""Ingest only the first 100 unique audited corpus documents into Supabase."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

import psycopg

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.db.connection import connect_database
from app.db.queries import (
    apply_schema,
    cosine_search,
    insert_batch,
    read_database_metrics,
    verify_target_documents,
)
from app.embedding_smoke import MODEL_NAME
from app.ingestion.indexer import embed_documents, prepare_document
from app.model_cache import load_model


CORPUS_PATH = PROJECT_ROOT / "data" / "corpus.jsonl"
SCHEMA_PATH = PROJECT_ROOT / "migrations" / "schema.sql"
MAX_DOCUMENTS = 100
DEFAULT_BATCH_SIZE = 25


def load_first_unique_documents(path: Path, target: int = MAX_DOCUMENTS) -> tuple[list[dict[str, Any]], int]:
    """Read and validate no more than 100 unique content-addressed corpus rows."""
    if target != MAX_DOCUMENTS:
        raise ValueError("this milestone is fixed at exactly 100 documents")
    documents, seen = [], set()
    records_read = 0
    with path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            records_read += 1
            try:
                raw = json.loads(line)
                document = prepare_document(raw)
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                raise ValueError(f"invalid corpus record at line {line_number}: {type(exc).__name__}") from None
            if document["doc_id"] in seen:
                continue
            seen.add(document["doc_id"])
            documents.append(document)
            if len(documents) == target:
                return documents, records_read
    raise ValueError(f"corpus ended after {len(documents)} unique documents; 100 are required")


def run_ingestion(batch_size: int = DEFAULT_BATCH_SIZE) -> dict[str, Any]:
    """Embed locally, apply additive DDL, commit bounded batches, and verify reads."""
    if not 1 <= batch_size <= MAX_DOCUMENTS:
        raise ValueError("batch size must be between 1 and 100")
    documents, records_read = load_first_unique_documents(CORPUS_PATH)
    model = load_model(MODEL_NAME)
    embed_documents(documents, model, MODEL_NAME, batch_size=batch_size)
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    doc_ids = [document["doc_id"] for document in documents]
    expected_sources = sum(len(document["sources"]) for document in documents)
    expected_chunks = sum(len(document["chunks"]) for document in documents)

    inserted = {"documents_inserted": 0, "sources_inserted": 0, "chunks_inserted": 0}
    with connect_database(autocommit=True) as conn:
        conn.execute("SET statement_timeout = '30000'")
        with conn.transaction():
            before = read_database_metrics(conn)
            apply_schema(conn, schema_sql)
        for start in range(0, len(documents), batch_size):
            with conn.transaction():
                batch_result = insert_batch(conn, documents[start:start + batch_size])
            for key, value in batch_result.items():
                inserted[key] += value
        with conn.transaction():
            after = read_database_metrics(conn)
            state = verify_target_documents(conn, doc_ids)
            search_results = cosine_search(conn, documents[0]["chunks"][0]["embedding"], limit=5)

    if state["target_documents"] != MAX_DOCUMENTS:
        raise RuntimeError("database does not contain all 100 target documents")
    if state["target_sources"] != expected_sources or state["target_chunks"] != expected_chunks:
        raise RuntimeError("database provenance or chunk counts do not match the 100-document input")
    if state["orphan_target_chunks"] or state["wrong_dimension_target_embeddings"]:
        raise RuntimeError("database contains an orphan chunk or a non-384-dimensional embedding")
    distances = [result["cosine_distance"] for result in search_results]
    if not search_results or distances != sorted(distances):
        raise RuntimeError("cosine-distance query did not return ranked results")

    with connect_database(autocommit=True) as fresh_conn:
        fresh_conn.execute("SET statement_timeout = '30000'")
        fresh_state = verify_target_documents(fresh_conn, doc_ids)
    if (fresh_state["target_documents"] != MAX_DOCUMENTS
            or fresh_state["target_sources"] != expected_sources
            or fresh_state["target_chunks"] != expected_chunks
            or fresh_state["orphan_target_chunks"]
            or fresh_state["wrong_dimension_target_embeddings"]):
        raise RuntimeError("fresh database connection could not verify inserted rows")

    return {
        "status": "passed",
        "documents_requested": MAX_DOCUMENTS,
        "unique_documents_read": len(documents),
        "corpus_records_read": records_read,
        "embedding_model": MODEL_NAME,
        "embedding_dimensions": 384,
        "chunking_strategy": "paragraph",
        "batch_size": batch_size,
        "inserted": inserted,
        "database_before": before,
        "database_after": after,
        "verified_state": state,
        "fresh_connection_read_passed": True,
        "cosine_search": {
            "query_vector_source": "first ingested paragraph embedding",
            "ranked_results": search_results,
            "distance_ordered": True,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    args = parser.parse_args()
    try:
        report = run_ingestion(args.batch_size)
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
