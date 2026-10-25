"""Safely ingest the approved HotpotQA corpus in resumable Phase 5 stages."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import psycopg

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.db.connection import EXPECTED_SUPABASE_PROJECT_REF, connect_database
from app.db.queries import (
    CHUNKS_SELECT_SQL,
    DOCUMENTS_SELECT_SQL,
    SOURCES_SELECT_SQL,
    insert_batch,
    read_database_document_ids,
    read_database_metrics,
    verify_target_documents,
)
from app.embedding_smoke import MODEL_NAME
from app.ingestion.indexer import embed_documents, prepare_document
from app.model_cache import load_model


CORPUS_PATH = PROJECT_ROOT / "data" / "corpus.jsonl"
PHASE5_PROJECT_REF = "nldnpqhqrfwjgxcqeuru"
MAX_DOCUMENTS = 50_000
VERIFIED_BASELINE_DOCUMENTS = 1_000
STAGE_TARGETS = (10_000, 25_000, 40_000, 50_000)
TARGET_TABLES = {"documents", "document_sources", "chunks"}
DEFAULT_BATCH_SIZE = 100
DEFAULT_THREADS = 4
DEFAULT_CHECKPOINT_EVERY = 500
VERIFY_BATCH_DOCUMENTS = 500
DATABASE_WARNING_BYTES = 450_000_000
DATABASE_CRITICAL_BYTES = 500_000_000
FREE_DISK_BUDGET_BYTES = 2 * 1024**3
SAFE_DISK_BUDGET_BYTES = int(FREE_DISK_BUDGET_BYTES * 0.95)
WAL_RESERVE_FACTOR = 1.25
STATEMENT_TIMEOUT = "120000"
ADVISORY_LOCK_ID = 2_716_504_050


class CapacityGateError(RuntimeError):
    """Stop before another batch or stage when a capacity gate fails."""

    def __init__(self, message: str, *, current_documents: int | None = None):
        super().__init__(message)
        self.current_documents = current_documents


def validate_stage_target(target: int) -> int:
    if target not in STAGE_TARGETS or target > MAX_DOCUMENTS:
        raise ValueError(f"Phase 5 target must be one of {STAGE_TARGETS}")
    return target


def validate_stage_transition(target: int, current_documents: int) -> None:
    """Require the previous checkpoint before entering the next stage."""
    validate_stage_target(target)
    previous_targets = [value for value in STAGE_TARGETS if value < target]
    required = max(previous_targets, default=VERIFIED_BASELINE_DOCUMENTS)
    if current_documents < required:
        raise ValueError(
            f"stage {target} requires the prior {required}-document checkpoint; "
            f"database has {current_documents}"
        )
    if current_documents > target:
        raise ValueError(
            f"database already has {current_documents} documents, beyond target {target}"
        )


def load_unique_prefix(path: Path, target: int) -> tuple[list[dict[str, Any]], int]:
    """Prepare the first target unique corpus documents with stable IDs."""
    if not 1 <= target <= MAX_DOCUMENTS:
        raise ValueError(f"document target must be between 1 and {MAX_DOCUMENTS}")
    documents: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    records_read = 0
    with path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            records_read += 1
            try:
                row = json.loads(line)
                document = prepare_document(row)
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                raise ValueError(
                    f"invalid corpus record at line {line_number}: {type(exc).__name__}"
                ) from None
            if document["doc_id"] in seen_ids:
                continue
            seen_ids.add(document["doc_id"])
            documents.append(document)
            if len(documents) == target:
                return documents, records_read
    raise ValueError(
        f"corpus ended after {len(documents)} unique documents; {target} required"
    )


def estimate_final_database_size(
    metrics: Mapping[str, Any],
    current_documents: int,
    *,
    target_documents: int = MAX_DOCUMENTS,
    safety_margin: float = 0.25,
) -> dict[str, int]:
    """Project database size by scaling target relations, then add the margin."""
    if current_documents <= 0:
        raise ValueError("cannot project storage without indexed documents")
    if target_documents < current_documents or target_documents > MAX_DOCUMENTS:
        raise ValueError("projection target must be between current count and 50,000")
    if not 0 <= safety_margin <= 1:
        raise ValueError("safety margin must be between 0 and 1")
    database_bytes = int(metrics["database_size_bytes"])
    relation_bytes = sum(
        int(table["total_relation_size_bytes"])
        for table in metrics["tables"].values()
    )
    if relation_bytes > database_bytes:
        raise ValueError("target table relation sizes exceed total database size")
    non_target_bytes = database_bytes - relation_bytes
    scaled_relations = math.ceil(relation_bytes * target_documents / current_documents)
    linear_total = non_target_bytes + scaled_relations
    with_margin = math.ceil(linear_total * (1 + safety_margin))
    return {
        "current_database_bytes": database_bytes,
        "current_target_relation_bytes": relation_bytes,
        "non_target_database_bytes": non_target_bytes,
        "linear_50k_database_bytes": linear_total,
        "safety_margin_percent": round(safety_margin * 100),
        "projected_50k_database_bytes_with_margin": with_margin,
    }


def _verify_existing_schema(conn: Any) -> dict[str, Any]:
    """Read-only verification; Phase 5 never creates or alters schema objects."""
    relations = conn.execute(
        """SELECT c.relname, c.relkind, c.relrowsecurity
           FROM pg_catalog.pg_class AS c
           JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
           WHERE n.nspname = 'public' AND c.relkind IN ('r','p','v','m','f')
           ORDER BY c.relname"""
    ).fetchall()
    names = {row[0] for row in relations}
    if names != TARGET_TABLES or any(row[1] != "r" or not row[2] for row in relations):
        raise RuntimeError("public relations or RLS state differ from the approved Phase 1E schema")

    columns: dict[str, dict[str, str]] = {}
    for table, column, formatted_type in conn.execute(
        """SELECT c.relname, a.attname, format_type(a.atttypid, a.atttypmod)
           FROM pg_catalog.pg_class AS c
           JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
           JOIN pg_catalog.pg_attribute AS a ON a.attrelid = c.oid
           WHERE n.nspname = 'public' AND c.relname = ANY(%s)
             AND a.attnum > 0 AND NOT a.attisdropped""",
        (sorted(TARGET_TABLES),),
    ).fetchall():
        columns.setdefault(table, {})[column] = formatted_type
    expected_columns = {
        "documents": {
            "doc_id": "text", "content_hash": "text", "full_text": "text",
            "metadata": "jsonb",
        },
        "document_sources": {
            "source_id": "text", "doc_id": "text", "title_alias": "text",
            "title_normalized": "text", "source_url": "text",
            "source_revision": "text", "source_split": "text", "sentences": "jsonb",
        },
        "chunks": {
            "chunk_id": "text", "doc_id": "text", "chunk_position": "integer",
            "chunking_strategy": "text", "start_char": "integer", "end_char": "integer",
            "embedding": "halfvec(384)", "embedding_model": "text", "tsv": "tsvector",
        },
    }
    for table, expected in expected_columns.items():
        for column, expected_type in expected.items():
            actual_type = columns.get(table, {}).get(column)
            valid = (
                actual_type.endswith(expected_type)
                if expected_type == "halfvec(384)"
                else actual_type == expected_type
            )
            if not valid:
                raise RuntimeError(f"public.{table}.{column} has an unexpected type")
    if "chunk_text" in columns.get("chunks", {}):
        raise RuntimeError("chunks contains duplicate chunk_text; refusing Phase 5 writes")

    vector = conn.execute(
        """SELECT n.nspname, e.extversion
           FROM pg_catalog.pg_extension AS e
           JOIN pg_catalog.pg_namespace AS n ON n.oid = e.extnamespace
           WHERE e.extname = 'vector'"""
    ).fetchone()
    if not vector or vector[0] != "extensions":
        raise RuntimeError("pgvector is not installed in the approved extensions schema")

    indexes = conn.execute(
        """SELECT ic.relname, am.amname, i.indisvalid, pg_get_indexdef(i.indexrelid)
           FROM pg_catalog.pg_index AS i
           JOIN pg_catalog.pg_class AS ic ON ic.oid = i.indexrelid
           JOIN pg_catalog.pg_class AS tbl ON tbl.oid = i.indrelid
           JOIN pg_catalog.pg_namespace AS n ON n.oid = tbl.relnamespace
           JOIN pg_catalog.pg_am AS am ON am.oid = ic.relam
           WHERE n.nspname = 'public' AND tbl.relname = 'chunks'"""
    ).fetchall()
    index_map = {row[0]: row for row in indexes}
    hnsw = index_map.get("chunks_embedding_hnsw_idx")
    gin = index_map.get("chunks_tsv_gin_idx")
    if not hnsw or hnsw[1] != "hnsw" or not hnsw[2] or "halfvec_cosine_ops" not in hnsw[3]:
        raise RuntimeError("approved halfvec HNSW index is missing or invalid")
    if not gin or gin[1] != "gin" or not gin[2] or "tsv" not in gin[3]:
        raise RuntimeError("approved chunk FTS GIN index is missing or invalid")

    privilege_rows = conn.execute(
        """SELECT c.relname, r.role_name, p.privilege,
                  has_table_privilege(r.role_name, c.oid, p.privilege)
           FROM pg_catalog.pg_class AS c
           JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
           CROSS JOIN (VALUES ('anon'), ('authenticated'), ('service_role')) AS r(role_name)
           CROSS JOIN (VALUES ('SELECT'), ('INSERT'), ('UPDATE'), ('DELETE')) AS p(privilege)
           WHERE n.nspname = 'public' AND c.relname = ANY(%s)
           ORDER BY c.relname, r.role_name, p.privilege""",
        (sorted(TARGET_TABLES),),
    ).fetchall()
    if len(privilege_rows) != len(TARGET_TABLES) * 12:
        raise RuntimeError("could not verify all Phase 1E table privileges")
    unexpected_grants = [
        row for row in privilege_rows
        if (row[1] in {"anon", "authenticated"} and row[3])
        or (row[1] == "service_role" and not row[3])
    ]
    public_grants = conn.execute(
        """SELECT c.relname, x.privilege_type
           FROM pg_catalog.pg_class AS c
           JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
           CROSS JOIN LATERAL aclexplode(
               COALESCE(c.relacl, acldefault('r', c.relowner))
           ) AS x
           WHERE n.nspname = 'public' AND c.relname = ANY(%s) AND x.grantee = 0""",
        (sorted(TARGET_TABLES),),
    ).fetchall()
    if unexpected_grants or public_grants:
        raise RuntimeError("EvidenceAI table privileges differ from the approved backend-only grants")
    return {
        "public_relations": sorted(names),
        "rls_enabled": True,
        "vector_extension_version": vector[1],
        "hnsw_index_valid": True,
        "gin_index_valid": True,
        "backend_only_grants_verified": True,
    }


def _read_wal_storage(conn: Any) -> dict[str, int]:
    files, bytes_used = conn.execute(
        "SELECT count(*), COALESCE(sum(size), 0) FROM pg_catalog.pg_ls_waldir()"
    ).fetchone()
    max_wal_bytes = conn.execute(
        "SELECT pg_size_bytes(current_setting('max_wal_size'))"
    ).fetchone()[0]
    return {
        "wal_files": int(files),
        "wal_bytes": int(bytes_used),
        "max_wal_size_bytes": int(max_wal_bytes),
    }


def _capacity_snapshot(
    metrics: Mapping[str, Any],
    wal: Mapping[str, int],
    current_documents: int,
) -> dict[str, Any]:
    projection = estimate_final_database_size(metrics, current_documents)
    wal_reserve = math.ceil(
        max(int(wal["wal_bytes"]), int(wal["max_wal_size_bytes"])) * WAL_RESERVE_FACTOR
    )
    peak_disk_projection = projection["projected_50k_database_bytes_with_margin"] + wal_reserve
    return {
        **projection,
        "actual_wal_bytes": int(wal["wal_bytes"]),
        "max_wal_size_bytes": int(wal["max_wal_size_bytes"]),
        "wal_reserve_bytes": wal_reserve,
        "free_plan_disk_budget_bytes": FREE_DISK_BUDGET_BYTES,
        "safe_disk_usage_limit_bytes": SAFE_DISK_BUDGET_BYTES,
        "projected_peak_database_plus_wal_bytes": peak_disk_projection,
        "projected_safe_disk_headroom_bytes": SAFE_DISK_BUDGET_BYTES - peak_disk_projection,
    }


def _query_total_documents(conn: Any) -> int:
    return int(conn.execute("SELECT count(*) FROM public.documents").fetchone()[0])


def _compare_rows(
    expected: Mapping[str, tuple[Any, ...]],
    actual_rows: Sequence[Sequence[Any]],
    label: str,
) -> None:
    actual = {str(row[0]): tuple(row[1:]) for row in actual_rows}
    if actual != expected:
        raise RuntimeError(
            f"{label} corpus verification failed: "
            f"expected {len(expected)} rows, received {len(actual)} or content differed"
        )


def verify_exact_corpus_rows(
    conn: Any,
    documents: Sequence[Mapping[str, Any]],
    *,
    batch_documents: int = VERIFY_BATCH_DOCUMENTS,
) -> dict[str, int]:
    """Compare every stored document, source, and offset-reconstructed chunk."""
    verified = {"documents": 0, "sources": 0, "chunks": 0}
    for start in range(0, len(documents), batch_documents):
        batch = documents[start:start + batch_documents]
        doc_ids = [document["doc_id"] for document in batch]
        expected_docs = {
            document["doc_id"]: (
                document["content_hash"], document["full_text"], document["metadata"],
            )
            for document in batch
        }
        expected_sources = {
            source["source_id"]: (
                source["doc_id"], source["title_alias"], source["title_normalized"],
                source["source_url"], source["source_revision"], source["source_split"],
                source["sentences"],
            )
            for document in batch for source in document["sources"]
        }
        expected_chunks = {
            chunk["chunk_id"]: (
                chunk["doc_id"], chunk["chunk_position"], chunk["chunking_strategy"],
                chunk["start_char"], chunk["end_char"], chunk["chunk_text"], MODEL_NAME,
            )
            for document in batch for chunk in document["chunks"]
        }
        source_ids = list(expected_sources)
        chunk_ids = list(expected_chunks)
        _compare_rows(
            expected_docs,
            conn.execute(DOCUMENTS_SELECT_SQL, (doc_ids,)).fetchall(),
            "document",
        )
        _compare_rows(
            expected_sources,
            conn.execute(SOURCES_SELECT_SQL, (source_ids,)).fetchall(),
            "provenance",
        )
        _compare_rows(
            expected_chunks,
            conn.execute(CHUNKS_SELECT_SQL, (chunk_ids,)).fetchall(),
            "reconstructed chunk",
        )
        verified["documents"] += len(expected_docs)
        verified["sources"] += len(expected_sources)
        verified["chunks"] += len(expected_chunks)
    return verified


def _emit(
    callback: Callable[[dict[str, Any]], None] | None,
    event: str,
    **payload: Any,
) -> None:
    if callback is not None:
        callback({"event": event, **payload})


def _required_previous_checkpoint(target: int) -> int:
    prior = [checkpoint for checkpoint in STAGE_TARGETS if checkpoint < target]
    return max(prior, default=0)


def run_stage(
    target: int,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    threads: int = DEFAULT_THREADS,
    checkpoint_every: int = DEFAULT_CHECKPOINT_EVERY,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Resume safely from existing content IDs and commit bounded batches."""
    validate_stage_target(target)
    if not 1 <= batch_size <= 1_000:
        raise ValueError("batch size must be between 1 and 1,000")
    if not 1 <= threads <= 16:
        raise ValueError("embedding threads must be between 1 and 16")
    if checkpoint_every < batch_size:
        raise ValueError("checkpoint interval must be at least the batch size")
    if EXPECTED_SUPABASE_PROJECT_REF != PHASE5_PROJECT_REF:
        raise RuntimeError("application database guard does not match the Phase 5 Frankfurt target")

    total_started = time.perf_counter()
    corpus_started = time.perf_counter()
    documents, records_read = load_unique_prefix(CORPUS_PATH, target)
    corpus_seconds = time.perf_counter() - corpus_started
    doc_ids = [document["doc_id"] for document in documents]
    target_ids = set(doc_ids)
    expected_sources = sum(len(document["sources"]) for document in documents)
    expected_chunks = sum(len(document["chunks"]) for document in documents)
    if len(doc_ids) != len(target_ids):
        raise RuntimeError("corpus prefix has duplicate stable document IDs")

    inserted = {"documents_inserted": 0, "sources_inserted": 0, "chunks_inserted": 0}
    chunks_embedded = 0
    embedding_seconds = 0.0
    model_initialization_seconds = 0.0
    initial_database_count = 0
    database_started = time.perf_counter()
    schema_check: dict[str, Any] = {}
    exact_existing: dict[str, int] = {"documents": 0, "sources": 0, "chunks": 0}
    before: dict[str, Any] = {}
    capacity_before: dict[str, Any] = {}
    capacity_after: dict[str, Any] = {}
    state: dict[str, Any] = {}
    exact_all: dict[str, int] = {}
    lock_acquired = False

    with connect_database(autocommit=True) as conn:
        conn.execute(f"SET statement_timeout = '{STATEMENT_TIMEOUT}'")
        lock_acquired = bool(
            conn.execute("SELECT pg_try_advisory_lock(%s)", (ADVISORY_LOCK_ID,)).fetchone()[0]
        )
        if not lock_acquired:
            raise RuntimeError("another EvidenceAI Phase 5 ingestion process holds the database lock")
        try:
            schema_check = _verify_existing_schema(conn)
            before = read_database_metrics(conn)
            existing_ids = read_database_document_ids(conn)
            current_count = len(existing_ids)
            initial_database_count = current_count
            validate_stage_transition(target, current_count)
            if existing_ids - target_ids:
                raise RuntimeError(
                    "database contains documents outside the selected corpus prefix; refusing writes"
                )
            if _query_total_documents(conn) != current_count:
                raise RuntimeError("database document ID list and row count disagree")
            previous_checkpoint = _required_previous_checkpoint(target)
            if current_count < previous_checkpoint:
                raise RuntimeError(
                    f"stage requires {previous_checkpoint} existing documents; "
                    f"found {current_count}"
                )

            existing_documents = [
                document for document in documents if document["doc_id"] in existing_ids
            ]
            if existing_documents:
                existing_state = verify_target_documents(
                    conn, [document["doc_id"] for document in existing_documents],
                )
                existing_sources = sum(
                    len(document["sources"]) for document in existing_documents
                )
                existing_chunks = sum(
                    len(document["chunks"]) for document in existing_documents
                )
                if (
                    existing_state["target_documents"] != current_count
                    or existing_state["target_sources"] != existing_sources
                    or existing_state["target_chunks"] != existing_chunks
                    or existing_state["total_documents"] != current_count
                    or existing_state["total_sources"] != existing_sources
                    or existing_state["total_chunks"] != existing_chunks
                    or existing_state["orphan_target_chunks"]
                    or existing_state["orphan_target_sources"]
                    or existing_state["wrong_dimension_target_embeddings"]
                    or existing_state["invalid_target_chunk_offsets"]
                ):
                    raise RuntimeError("existing checkpoint failed relation/vector/offset integrity")
                exact_existing = verify_exact_corpus_rows(conn, existing_documents)

            wal_before = _read_wal_storage(conn)
            capacity_before = _capacity_snapshot(before, wal_before, max(current_count, 1))
            if before["database_size_bytes"] >= DATABASE_CRITICAL_BYTES:
                raise CapacityGateError(
                    "database is already at or above 500 MB; refusing all ingestion writes",
                    current_documents=current_count,
                )
            if current_count and current_count < MAX_DOCUMENTS:
                if (
                    target < MAX_DOCUMENTS
                    and before["database_size_bytes"] >= DATABASE_WARNING_BYTES
                ):
                    raise CapacityGateError(
                        "database is at or above the 450 MB intermediate safety limit",
                        current_documents=current_count,
                    )
                if capacity_before["projected_safe_disk_headroom_bytes"] <= 0:
                    raise CapacityGateError(
                        "projected database plus WAL leaves insufficient Free-plan disk headroom",
                        current_documents=current_count,
                    )
                if (
                    target > STAGE_TARGETS[0]
                    and capacity_before["projected_50k_database_bytes_with_margin"]
                    > DATABASE_WARNING_BYTES
                ):
                    raise CapacityGateError(
                        "50K projection with 25% margin exceeds 450 MB before this stage",
                        current_documents=current_count,
                    )

            missing_documents = [
                document for document in documents if document["doc_id"] not in existing_ids
            ]
            _emit(
                progress_callback,
                "stage_started",
                target_documents=target,
                existing_documents=current_count,
                missing_documents=len(missing_documents),
                corpus_records_read=records_read,
                project_ref=PHASE5_PROJECT_REF,
                threads=threads,
                batch_size=batch_size,
                capacity_before=capacity_before,
            )

            model = None
            if missing_documents:
                model_started = time.perf_counter()
                model = load_model(MODEL_NAME, threads=threads)
                model_initialization_seconds = time.perf_counter() - model_started

            next_checkpoint = checkpoint_every
            for start in range(0, len(missing_documents), batch_size):
                batch = missing_documents[start:start + batch_size]
                if model is None:
                    raise RuntimeError("embedding model was not initialized for missing documents")
                started = time.perf_counter()
                embed_documents(batch, model, MODEL_NAME, batch_size=batch_size)
                embedding_seconds += time.perf_counter() - started
                chunks_embedded += sum(len(document["chunks"]) for document in batch)
                with conn.transaction():
                    result = insert_batch(conn, batch)
                for key, value in result.items():
                    inserted[key] += value

                completed_this_run = min(start + len(batch), len(missing_documents))
                predicted_total = initial_database_count + inserted["documents_inserted"]
                live_database_bytes = int(
                    conn.execute("SELECT pg_database_size(current_database())").fetchone()[0]
                )
                if live_database_bytes >= DATABASE_CRITICAL_BYTES:
                    live_count = _query_total_documents(conn)
                    _emit(
                        progress_callback,
                        "critical_capacity_stop",
                        current_documents=live_count,
                        database_size_bytes=live_database_bytes,
                        threshold_bytes=DATABASE_CRITICAL_BYTES,
                    )
                    raise CapacityGateError(
                        "database reached 500 MB during ingestion; stopped before another batch",
                        current_documents=live_count,
                    )
                if target < MAX_DOCUMENTS and live_database_bytes >= DATABASE_WARNING_BYTES:
                    live_count = _query_total_documents(conn)
                    raise CapacityGateError(
                        "database reached 450 MB before the final 50K stage",
                        current_documents=live_count,
                    )

                if (
                    completed_this_run >= next_checkpoint
                    or completed_this_run == len(missing_documents)
                ):
                    actual_count = _query_total_documents(conn)
                    if actual_count != predicted_total:
                        raise RuntimeError(
                            f"checkpoint count mismatch: expected {predicted_total}, "
                            f"database reports {actual_count}"
                        )
                    progress_metrics = read_database_metrics(conn)
                    wal_now = _read_wal_storage(conn)
                    capacity_now = _capacity_snapshot(
                        progress_metrics, wal_now, max(actual_count, 1),
                    )
                    _emit(
                        progress_callback,
                        "batch_checkpoint",
                        target_documents=target,
                        processed_this_run=completed_this_run,
                        actual_document_count=actual_count,
                        database_size_bytes=progress_metrics["database_size_bytes"],
                        wal_bytes=wal_now["wal_bytes"],
                        projected_50k_with_margin_bytes=capacity_now[
                            "projected_50k_database_bytes_with_margin"
                        ],
                        projected_safe_disk_headroom_bytes=capacity_now[
                            "projected_safe_disk_headroom_bytes"
                        ],
                        inserted=inserted.copy(),
                    )
                    if capacity_now["projected_safe_disk_headroom_bytes"] <= 0:
                        raise CapacityGateError(
                            "projected database plus WAL leaves insufficient disk headroom",
                            current_documents=actual_count,
                        )
                    if (
                        target < MAX_DOCUMENTS
                        and capacity_now["projected_50k_database_bytes_with_margin"]
                        > DATABASE_WARNING_BYTES
                    ):
                        raise CapacityGateError(
                            "50K projection with 25% margin exceeded 450 MB at a checkpoint",
                            current_documents=actual_count,
                        )
                    next_checkpoint = completed_this_run + checkpoint_every

            expected_total = len(target_ids)
            actual_count = _query_total_documents(conn)
            if actual_count != expected_total:
                raise RuntimeError(
                    f"stage expected {expected_total} documents, database has {actual_count}"
                )

            # The existing HNSW index is maintained as rows are inserted. Do not
            # drop/rebuild it: rebuilding needs extra disk and can lose the index.
            conn.execute("ANALYZE public.documents")
            conn.execute("ANALYZE public.document_sources")
            conn.execute("ANALYZE public.chunks")

            state = verify_target_documents(conn, doc_ids)
            if (
                state["target_documents"] != target
                or state["target_sources"] != expected_sources
                or state["target_chunks"] != expected_chunks
                or state["total_documents"] != target
                or state["total_sources"] != expected_sources
                or state["total_chunks"] != expected_chunks
                or state["orphan_target_chunks"]
                or state["orphan_target_sources"]
                or state["wrong_dimension_target_embeddings"]
                or state["invalid_target_chunk_offsets"]
            ):
                raise RuntimeError("stage failed database relationship/vector/offset integrity")
            exact_all = verify_exact_corpus_rows(conn, documents)
            if exact_all != {
                "documents": target, "sources": expected_sources, "chunks": expected_chunks,
            }:
                raise RuntimeError("exact corpus integrity returned unexpected row totals")
            after = read_database_metrics(conn)
            wal_after = _read_wal_storage(conn)
            capacity_after = _capacity_snapshot(after, wal_after, target)
            final_state = _verify_existing_schema(conn)
        finally:
            if lock_acquired:
                conn.execute("SELECT pg_advisory_unlock(%s)", (ADVISORY_LOCK_ID,))

    fresh_started = time.perf_counter()
    with connect_database(autocommit=True) as fresh_conn:
        fresh_conn.execute(f"SET statement_timeout = '{STATEMENT_TIMEOUT}'")
        fresh_state = verify_target_documents(fresh_conn, doc_ids)
    fresh_read_seconds = time.perf_counter() - fresh_started
    if (
        fresh_state["target_documents"] != target
        or fresh_state["target_sources"] != expected_sources
        or fresh_state["target_chunks"] != expected_chunks
        or fresh_state["total_documents"] != target
        or fresh_state["total_sources"] != expected_sources
        or fresh_state["total_chunks"] != expected_chunks
        or fresh_state["orphan_target_chunks"]
        or fresh_state["orphan_target_sources"]
        or fresh_state["wrong_dimension_target_embeddings"]
        or fresh_state["invalid_target_chunk_offsets"]
    ):
        raise RuntimeError("fresh connection failed the stage integrity read")

    current_database_bytes = int(after["database_size_bytes"])
    projection_bytes = int(capacity_after["projected_50k_database_bytes_with_margin"])
    if current_database_bytes >= DATABASE_CRITICAL_BYTES:
        gate = "critical_capacity_failure"
        continue_allowed = False
    elif target == MAX_DOCUMENTS:
        if current_database_bytes <= DATABASE_WARNING_BYTES:
            gate = "passed"
            continue_allowed = False
        else:
            gate = "warning_pending_owner_review"
            continue_allowed = False
    elif current_database_bytes >= DATABASE_WARNING_BYTES:
        gate = "stop_actual_size_limit"
        continue_allowed = False
    elif projection_bytes > DATABASE_WARNING_BYTES:
        gate = "stop_projected_size_limit"
        continue_allowed = False
    elif capacity_after["projected_safe_disk_headroom_bytes"] <= 0:
        gate = "stop_insufficient_disk_headroom"
        continue_allowed = False
    else:
        gate = "continue"
        continue_allowed = True

    return {
        "status": "passed" if state else "failed",
        "stage_target_documents": target,
        "project_ref": PHASE5_PROJECT_REF,
        "corpus_unique_documents_read": len(documents),
        "corpus_records_read": records_read,
        "chunking_strategy": "paragraph",
        "embedding_model": MODEL_NAME,
        "embedding_dimensions": 384,
        "embedding_threads": threads,
        "batch_size": batch_size,
        "existing_documents_before": initial_database_count,
        "inserted": inserted,
        "actual_document_count_after": state["total_documents"],
        "provenance_count_after": state["total_sources"],
        "chunk_count_after": state["total_chunks"],
        "expected_provenance": expected_sources,
        "expected_chunks": expected_chunks,
        "integrity": state,
        "exact_existing_rows_checked_before_resume": exact_existing,
        "exact_corpus_rows_checked_after_stage": exact_all,
        "fresh_connection_read_passed": True,
        "fresh_connection_read_seconds": round(fresh_read_seconds, 3),
        "schema_security_indexes": final_state,
        "capacity_gate": gate,
        "continue_allowed": continue_allowed,
        "database_before": before,
        "database_after_analyze": after,
        "wal_before": wal_before,
        "wal_after": wal_after,
        "capacity_projection_before": capacity_before,
        "capacity_projection_after": capacity_after,
        "timings_seconds": {
            "corpus_prepare": round(corpus_seconds, 3),
            "model_initialization": round(model_initialization_seconds, 3),
            "embedding_generation": round(embedding_seconds, 3),
            "database_write_analyze_and_verify": round(
                time.perf_counter() - database_started, 3,
            ),
            "total": round(time.perf_counter() - total_started, 3),
        },
        "chunks_embedded_this_run": chunks_embedded,
    }


def _read_current_document_count() -> int | None:
    try:
        with connect_database(autocommit=True) as conn:
            return _query_total_documents(conn)
    except Exception:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, required=True, choices=STAGE_TARGETS)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--threads", type=int, default=DEFAULT_THREADS)
    parser.add_argument("--checkpoint-every", type=int, default=DEFAULT_CHECKPOINT_EVERY)
    args = parser.parse_args()

    def emit(event: dict[str, Any]) -> None:
        print(json.dumps(event, sort_keys=True), flush=True)

    try:
        report = run_stage(
            args.limit,
            batch_size=args.batch_size,
            threads=args.threads,
            checkpoint_every=args.checkpoint_every,
            progress_callback=emit,
        )
    except CapacityGateError as exc:
        emit({
            "status": "capacity_abort",
            "error": str(exc),
            "current_document_count": (
                exc.current_documents
                if exc.current_documents is not None
                else _read_current_document_count()
            ),
        })
        return 2
    except psycopg.Error as exc:
        emit({
            "status": "failed",
            "error_type": type(exc).__name__,
            "sqlstate": exc.sqlstate,
            "current_document_count": _read_current_document_count(),
        })
        return 1
    except (OSError, ValueError, RuntimeError) as exc:
        emit({
            "status": "failed",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "current_document_count": _read_current_document_count(),
        })
        return 1

    emit({"event": "stage_complete", **report})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
