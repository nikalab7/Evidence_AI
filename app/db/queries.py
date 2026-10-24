"""Parameterized PostgreSQL writes and measurements for the ingestion milestone."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from psycopg import Connection, sql
from psycopg.types.json import Jsonb


TARGET_TABLES = ("documents", "document_sources", "chunks")

DOCUMENTS_UPSERT_SQL = """
INSERT INTO public.documents (doc_id, content_hash, full_text, metadata)
SELECT incoming.doc_id, incoming.content_hash, incoming.full_text, incoming.metadata
FROM jsonb_to_recordset(%s::jsonb) AS incoming(
    doc_id text, content_hash text, full_text text, metadata jsonb
)
ON CONFLICT (doc_id) DO NOTHING
RETURNING doc_id
"""

SOURCES_UPSERT_SQL = """
INSERT INTO public.document_sources (
    source_id, doc_id, title_alias, title_normalized, source_url,
    source_revision, source_split, sentences
)
SELECT incoming.source_id, incoming.doc_id, incoming.title_alias,
       incoming.title_normalized, incoming.source_url, incoming.source_revision,
       incoming.source_split, incoming.sentences
FROM jsonb_to_recordset(%s::jsonb) AS incoming(
    source_id text, doc_id text, title_alias text, title_normalized text,
    source_url text, source_revision text, source_split text, sentences jsonb
)
ON CONFLICT (source_id) DO NOTHING
RETURNING source_id
"""

CHUNKS_UPSERT_SQL = """
INSERT INTO public.chunks (
    chunk_id, doc_id, chunk_position, chunking_strategy, chunk_text,
    embedding, embedding_model
)
SELECT incoming.chunk_id, incoming.doc_id, incoming.chunk_position,
       incoming.chunking_strategy, incoming.chunk_text,
       incoming.embedding::extensions.vector(384), incoming.embedding_model
FROM jsonb_to_recordset(%s::jsonb) AS incoming(
    chunk_id text, doc_id text, chunk_position integer, chunking_strategy text,
    chunk_text text, embedding text, embedding_model text
)
ON CONFLICT (chunk_id) DO NOTHING
RETURNING chunk_id
"""

DOCUMENTS_SELECT_SQL = """
SELECT doc_id, content_hash, full_text, metadata
FROM public.documents WHERE doc_id = ANY(%s)
"""
SOURCES_SELECT_SQL = """
SELECT source_id, doc_id, title_alias, title_normalized, source_url,
       source_revision, source_split, sentences
FROM public.document_sources WHERE source_id = ANY(%s)
"""
CHUNKS_SELECT_SQL = """
SELECT chunk_id, doc_id, chunk_position, chunking_strategy, chunk_text, embedding_model
FROM public.chunks WHERE chunk_id = ANY(%s)
"""


def apply_schema(conn: Connection, schema_sql: str) -> None:
    """Apply only additive DDL after confirming pgvector and any existing tables."""
    vector = conn.execute(
        """SELECT n.nspname FROM pg_extension e
           JOIN pg_namespace n ON n.oid = e.extnamespace WHERE e.extname = 'vector'"""
    ).fetchone()
    if not vector or vector[0] != "extensions":
        raise RuntimeError("pgvector must be installed in the extensions schema")
    can_create = conn.execute(
        "SELECT has_schema_privilege(current_user, 'public', 'CREATE')"
    ).fetchone()[0]
    if not can_create:
        raise RuntimeError("database role cannot create tables in public")
    _check_existing_tables(conn)
    conn.execute(schema_sql)
    _check_existing_tables(conn, require_all=True)


def _check_existing_tables(conn: Connection, *, require_all: bool = False) -> None:
    expected = {
        "documents": {"doc_id": "text", "content_hash": "text", "full_text": "text", "metadata": "jsonb"},
        "document_sources": {
            "source_id": "text", "doc_id": "text", "title_alias": "text",
            "title_normalized": "text", "source_url": "text", "source_revision": "text",
            "source_split": "text", "sentences": "jsonb",
        },
        "chunks": {
            "chunk_id": "text", "doc_id": "text", "chunk_position": "integer",
            "chunking_strategy": "text", "chunk_text": "text", "embedding": "vector(384)",
            "embedding_model": "text", "tsv": "tsvector",
        },
    }
    relations = dict(conn.execute(
        """SELECT table_name, table_type FROM information_schema.tables
           WHERE table_schema = 'public' AND table_name = ANY(%s)""",
        (list(TARGET_TABLES),),
    ).fetchall())
    if require_all and any(name not in relations for name in TARGET_TABLES):
        raise RuntimeError("ingestion schema did not create every target table")
    columns: dict[str, dict[str, str]] = {name: {} for name in TARGET_TABLES}
    for table, column, formatted_type in conn.execute(
        """SELECT c.relname, a.attname, format_type(a.atttypid, a.atttypmod)
           FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
           JOIN pg_attribute a ON a.attrelid = c.oid
           WHERE n.nspname = 'public' AND c.relname = ANY(%s)
             AND a.attnum > 0 AND NOT a.attisdropped""",
        (list(TARGET_TABLES),),
    ).fetchall():
        columns[table][column] = formatted_type
    for table, table_type in relations.items():
        if table_type != "BASE TABLE":
            raise RuntimeError(f"public.{table} exists but is not a base table; refusing schema changes")
        for column, expected_type in expected[table].items():
            actual_type = columns[table].get(column)
            type_matches = (actual_type.endswith("vector(384)") if expected_type == "vector(384)"
                            else actual_type == expected_type)
            if not type_matches:
                raise RuntimeError(f"public.{table} has an incompatible {column} column; refusing schema changes")


def read_database_metrics(conn: Connection) -> dict[str, Any]:
    """Measure database, heap, index, row, and vector-column storage."""
    database_size = conn.execute("SELECT pg_database_size(current_database())").fetchone()[0]
    tables: dict[str, dict[str, int]] = {}
    indexes: list[dict[str, Any]] = []
    for table in TARGET_TABLES:
        relation = conn.execute("SELECT to_regclass(%s)", (f"public.{table}",)).fetchone()[0]
        if relation is None:
            tables[table] = {
                "rows": 0, "heap_bytes": 0, "table_storage_bytes": 0,
                "index_bytes": 0, "total_relation_size_bytes": 0,
            }
            continue
        query = sql.SQL(
            "SELECT count(*), pg_relation_size(%s::regclass), pg_table_size(%s::regclass), "
            "pg_indexes_size(%s::regclass), pg_total_relation_size(%s::regclass) "
            "FROM {}.{}"
        ).format(sql.Identifier("public"), sql.Identifier(table))
        count, heap_size, table_size, index_size, total_size = conn.execute(
            query, (f"public.{table}",) * 4,
        ).fetchone()
        tables[table] = {
            "rows": count,
            "heap_bytes": heap_size,
            "table_storage_bytes": table_size,
            "index_bytes": index_size,
            "total_relation_size_bytes": total_size,
        }
        for name, size in conn.execute(
            """SELECT quote_ident(ns.nspname)||'.'||quote_ident(idx.relname),
                      pg_relation_size(idx.oid)
               FROM pg_index pi
               JOIN pg_class tbl ON tbl.oid = pi.indrelid
               JOIN pg_namespace tbl_ns ON tbl_ns.oid = tbl.relnamespace
               JOIN pg_class idx ON idx.oid = pi.indexrelid
               JOIN pg_namespace ns ON ns.oid = idx.relnamespace
               WHERE tbl_ns.nspname = 'public' AND tbl.relname = %s
               ORDER BY idx.relname""",
            (table,),
        ).fetchall():
            indexes.append({"table": table, "name": name, "main_fork_bytes": size})

    if tables["chunks"]["rows"]:
        embedding_rows, embedding_bytes, average_embedding_bytes = conn.execute(
            """SELECT count(*), COALESCE(sum(pg_column_size(embedding)), 0),
                      COALESCE(avg(pg_column_size(embedding)), 0)
               FROM public.chunks""",
        ).fetchone()
    else:
        embedding_rows, embedding_bytes, average_embedding_bytes = 0, 0, 0
    return {
        "database_size_bytes": database_size,
        "tables": tables,
        "indexes": indexes,
        "embedding_storage": {
            "rows": embedding_rows,
            "value_bytes_total": embedding_bytes,
            "value_bytes_average": round(float(average_embedding_bytes), 2),
            "note": "pg_column_size of vector values; excludes chunk row overhead and HNSW index",
        },
    }


def read_database_document_ids(conn: Connection) -> set[str]:
    """Return current document IDs, or an empty set before the table is created."""
    relation = conn.execute("SELECT to_regclass('public.documents')").fetchone()[0]
    if relation is None:
        return set()
    return {row[0] for row in conn.execute("SELECT doc_id FROM public.documents").fetchall()}


def insert_batch(conn: Connection, documents: Sequence[dict[str, Any]]) -> dict[str, int]:
    """Insert one transaction batch without updating or deleting existing records."""
    document_rows, source_rows, chunk_rows = [], [], []
    for document in documents:
        document_rows.append({key: document[key] for key in (
            "doc_id", "content_hash", "full_text", "metadata",
        )})
        source_rows.extend(document["sources"])
        for chunk in document["chunks"]:
            if chunk["embedding"] is None or chunk["embedding_model"] is None:
                raise ValueError("every chunk must be embedded before database insertion")
            chunk_rows.append({key: chunk[key] for key in (
                "chunk_id", "doc_id", "chunk_position", "chunking_strategy", "chunk_text",
                "embedding", "embedding_model",
            )})

    inserted_documents = _insert_ids(conn, DOCUMENTS_UPSERT_SQL, document_rows)
    inserted_sources = _insert_ids(conn, SOURCES_UPSERT_SQL, source_rows)
    inserted_chunks = _insert_ids(conn, CHUNKS_UPSERT_SQL, chunk_rows)
    _verify_document_rows(conn, document_rows)
    _verify_source_rows(conn, source_rows)
    _verify_chunk_rows(conn, chunk_rows)
    return {
        "documents_inserted": len(inserted_documents),
        "sources_inserted": len(inserted_sources),
        "chunks_inserted": len(inserted_chunks),
    }


def _insert_ids(conn: Connection, statement: str, rows: list[dict[str, Any]]) -> set[str]:
    if not rows:
        return set()
    result = conn.execute(statement, (Jsonb(rows),))
    return {row[0] for row in result.fetchall()}


def _verify_rows(
    conn: Connection,
    statement: str,
    rows: list[dict[str, Any]],
    id_field: str,
    fields: tuple[str, ...],
    label: str,
) -> None:
    if not rows:
        return
    expected = {row[id_field]: tuple(row[field] for field in fields[1:]) for row in rows}
    actual = {row[0]: tuple(row[1:]) for row in conn.execute(
        statement, (list(expected),),
    ).fetchall()}
    if actual != expected:
        raise RuntimeError(f"existing {label} rows do not match the requested content; no rows were overwritten")


def _verify_document_rows(conn: Connection, rows: list[dict[str, Any]]) -> None:
    _verify_rows(conn, DOCUMENTS_SELECT_SQL, rows, "doc_id",
                 ("doc_id", "content_hash", "full_text", "metadata"), "document")


def _verify_source_rows(conn: Connection, rows: list[dict[str, Any]]) -> None:
    fields = ("source_id", "doc_id", "title_alias", "title_normalized", "source_url",
              "source_revision", "source_split", "sentences")
    _verify_rows(conn, SOURCES_SELECT_SQL, rows, "source_id", fields, "provenance")


def _verify_chunk_rows(conn: Connection, rows: list[dict[str, Any]]) -> None:
    fields = ("chunk_id", "doc_id", "chunk_position", "chunking_strategy", "chunk_text", "embedding_model")
    _verify_rows(conn, CHUNKS_SELECT_SQL, rows, "chunk_id", fields, "chunk")


def verify_target_documents(conn: Connection, doc_ids: Sequence[str]) -> dict[str, int]:
    """Check document, provenance, chunk, vector-dimension, and foreign-key integrity."""
    target_docs = conn.execute(
        "SELECT count(*) FROM public.documents WHERE doc_id = ANY(%s)", (list(doc_ids),),
    ).fetchone()[0]
    source_count = conn.execute(
        "SELECT count(*) FROM public.document_sources WHERE doc_id = ANY(%s)", (list(doc_ids),),
    ).fetchone()[0]
    chunk_count = conn.execute(
        "SELECT count(*) FROM public.chunks WHERE doc_id = ANY(%s)", (list(doc_ids),),
    ).fetchone()[0]
    orphan_count = conn.execute(
        """SELECT count(*) FROM public.chunks c LEFT JOIN public.documents d ON d.doc_id = c.doc_id
           WHERE c.doc_id = ANY(%s) AND d.doc_id IS NULL""",
        (list(doc_ids),),
    ).fetchone()[0]
    orphan_source_count = conn.execute(
        """SELECT count(*) FROM public.document_sources s
           LEFT JOIN public.documents d ON d.doc_id = s.doc_id
           WHERE s.doc_id = ANY(%s) AND d.doc_id IS NULL""",
        (list(doc_ids),),
    ).fetchone()[0]
    wrong_dimensions = conn.execute(
        """SELECT count(*) FROM public.chunks
           WHERE doc_id = ANY(%s) AND extensions.vector_dims(embedding) <> 384""",
        (list(doc_ids),),
    ).fetchone()[0]
    total_documents = conn.execute("SELECT count(*) FROM public.documents").fetchone()[0]
    total_chunks = conn.execute("SELECT count(*) FROM public.chunks").fetchone()[0]
    return {
        "target_documents": target_docs,
        "target_sources": source_count,
        "target_chunks": chunk_count,
        "orphan_target_chunks": orphan_count,
        "orphan_target_sources": orphan_source_count,
        "wrong_dimension_target_embeddings": wrong_dimensions,
        "total_documents": total_documents,
        "total_chunks": total_chunks,
    }


def cosine_search(conn: Connection, vector: Sequence[float], limit: int = 5) -> list[dict[str, Any]]:
    """Run a real PostgreSQL pgvector cosine-distance query in ascending rank order."""
    literal = "[" + ",".join(format(float(value), ".9g") for value in vector) + "]"
    rows = conn.execute(
        """WITH query_vector AS (SELECT %s::extensions.vector(384) AS embedding)
           SELECT c.chunk_id, c.doc_id, c.chunk_position,
                  c.embedding OPERATOR(extensions.<=>) q.embedding AS cosine_distance
           FROM public.chunks c CROSS JOIN query_vector q
           ORDER BY c.embedding OPERATOR(extensions.<=>) q.embedding, c.chunk_id
           LIMIT %s""",
        (literal, limit),
    ).fetchall()
    return [{
        "chunk_id": row[0], "doc_id": row[1], "chunk_position": row[2],
        "cosine_distance": float(row[3]),
    } for row in rows]
