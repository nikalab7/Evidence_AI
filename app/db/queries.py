"""Parameterized PostgreSQL writes and measurements for the ingestion milestone."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from psycopg import Connection, sql
from psycopg.types.json import Jsonb


TARGET_TABLES = ("documents", "document_sources", "chunks")
MANAGED_UPLOADS_TABLE = "managed_uploads"
APPROVED_PUBLIC_TABLES = frozenset((*TARGET_TABLES, MANAGED_UPLOADS_TABLE))

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
    chunk_id, doc_id, chunk_position, chunking_strategy, start_char, end_char,
    embedding, embedding_model
)
SELECT incoming.chunk_id, incoming.doc_id, incoming.chunk_position,
       incoming.chunking_strategy, incoming.start_char, incoming.end_char,
       incoming.embedding::extensions.halfvec(384), incoming.embedding_model
FROM jsonb_to_recordset(%s::jsonb) AS incoming(
    chunk_id text, doc_id text, chunk_position integer, chunking_strategy text,
    start_char integer, end_char integer, chunk_text text,
    embedding text, embedding_model text
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
SELECT c.chunk_id, c.doc_id, c.chunk_position, c.chunking_strategy,
       c.start_char, c.end_char,
       substring(d.full_text FROM c.start_char + 1 FOR c.end_char - c.start_char),
       c.embedding_model
FROM public.chunks AS c JOIN public.documents AS d ON d.doc_id = c.doc_id
WHERE c.chunk_id = ANY(%s)
"""


def apply_schema(conn: Connection, schema_sql: str) -> None:
    """Apply additive optimized DDL only in the dedicated, expected project."""
    public_relations = conn.execute(
        """SELECT table_name FROM information_schema.tables
           WHERE table_schema = 'public' ORDER BY table_name"""
    ).fetchall()
    relation_names = {row[0] for row in public_relations}
    has_managed_uploads = validate_approved_public_relations(relation_names)
    if has_managed_uploads:
        verify_managed_uploads_schema(conn, require_empty=True)
    can_create = conn.execute(
        "SELECT has_schema_privilege(current_user, 'public', 'CREATE')"
    ).fetchone()[0]
    if not can_create:
        raise RuntimeError("database role cannot create tables in public")
    _check_existing_tables(conn)
    conn.execute(schema_sql)
    _check_existing_tables(conn, require_all=True)
    relations_after = conn.execute(
        """SELECT table_name FROM information_schema.tables
           WHERE table_schema = 'public' ORDER BY table_name"""
    ).fetchall()
    has_managed_uploads_after = validate_approved_public_relations(
        {row[0] for row in relations_after},
    )
    if has_managed_uploads_after:
        verify_managed_uploads_schema(conn, require_empty=True)
    vector = conn.execute(
        """SELECT n.nspname FROM pg_extension e
           JOIN pg_namespace n ON n.oid = e.extnamespace WHERE e.extname = 'vector'"""
    ).fetchone()
    if not vector or vector[0] != "extensions":
        raise RuntimeError("pgvector must be installed in the extensions schema")
    security = conn.execute(
        """SELECT c.relname, c.relrowsecurity,
                  has_table_privilege('anon', c.oid, 'SELECT'),
                  has_table_privilege('authenticated', c.oid, 'SELECT'),
                  has_table_privilege('service_role', c.oid, 'SELECT')
           FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
           WHERE n.nspname = 'public' AND c.relname = ANY(%s)
           ORDER BY c.relname""",
        (list(TARGET_TABLES),),
    ).fetchall()
    if (len(security) != len(TARGET_TABLES)
            or any(not row[1] or row[2] or row[3] or not row[4] for row in security)):
        raise RuntimeError("EvidenceAI tables have unexpected RLS or role grants")


def validate_approved_public_relations(relation_names: Iterable[str]) -> bool:
    """Reject every public relation except the core tables and approved add-on."""
    names = set(relation_names)
    unexpected = names - APPROVED_PUBLIC_TABLES
    if unexpected:
        raise RuntimeError(
            "public schema contains unexpected tables; refusing database operation: "
            + ", ".join(sorted(unexpected))
        )
    return MANAGED_UPLOADS_TABLE in names


def verify_managed_uploads_schema(
    conn: Connection, *, require_empty: bool,
) -> bool:
    """Validate the sole approved add-on table and its exact access contract.

    Legacy corpus ingestion may continue only while this table is empty. The
    routine is read-only and deliberately rejects similarly named but
    incompatible or partially installed objects.
    """
    relation = conn.execute(
        """SELECT table_type FROM information_schema.tables
           WHERE table_schema = 'public' AND table_name = %s""",
        (MANAGED_UPLOADS_TABLE,),
    ).fetchone()
    if relation is None:
        return False
    if relation[0] != "BASE TABLE":
        raise RuntimeError("public.managed_uploads is not an approved base table")

    table = conn.execute(
        """SELECT c.oid, c.relkind, c.relrowsecurity,
                  has_table_privilege('anon', c.oid, 'SELECT'),
                  has_table_privilege('anon', c.oid, 'INSERT'),
                  has_table_privilege('anon', c.oid, 'UPDATE'),
                  has_table_privilege('anon', c.oid, 'DELETE'),
                  has_table_privilege('authenticated', c.oid, 'SELECT'),
                  has_table_privilege('authenticated', c.oid, 'INSERT'),
                  has_table_privilege('authenticated', c.oid, 'UPDATE'),
                  has_table_privilege('authenticated', c.oid, 'DELETE'),
                  has_table_privilege('service_role', c.oid, 'SELECT'),
                  has_table_privilege('service_role', c.oid, 'INSERT'),
                  has_table_privilege('service_role', c.oid, 'UPDATE'),
                  has_table_privilege('service_role', c.oid, 'DELETE')
           FROM pg_catalog.pg_class c
           JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
           WHERE n.nspname = 'public' AND c.relname = %s""",
        (MANAGED_UPLOADS_TABLE,),
    ).fetchone()
    if not table or table[1] != "r" or not table[2]:
        raise RuntimeError("managed_uploads must be a base table with RLS enabled")
    if any(table[index] for index in range(3, 11)) or not all(table[index] for index in range(11, 15)):
        raise RuntimeError("managed_uploads grants must be backend-only")

    public_grants = conn.execute(
        """SELECT 1 FROM pg_catalog.pg_class c
           CROSS JOIN LATERAL aclexplode(
               COALESCE(c.relacl, acldefault('r', c.relowner))
           ) acl
           WHERE c.oid = %s AND acl.grantee = 0 LIMIT 1""",
        (table[0],),
    ).fetchone()
    policies = conn.execute(
        "SELECT 1 FROM pg_catalog.pg_policy WHERE polrelid = %s LIMIT 1",
        (table[0],),
    ).fetchone()
    triggers = conn.execute(
        "SELECT 1 FROM pg_catalog.pg_trigger WHERE tgrelid = %s AND NOT tgisinternal LIMIT 1",
        (table[0],),
    ).fetchone()
    if public_grants or policies or triggers:
        raise RuntimeError("managed_uploads must have no PUBLIC grants, RLS policies, or triggers")

    expected_columns = {
        "upload_id": ("uuid", True), "doc_id": ("text", True),
        "source_id": ("text", True), "original_filename": ("text", True),
        "file_format": ("text", True), "title": ("text", True),
        "file_size_bytes": ("integer", True), "chunking_strategy": ("text", True),
        "parser_metadata": ("jsonb", True),
        "uploaded_at": ("timestamp with time zone", True),
        "updated_at": ("timestamp with time zone", True), "row_version": ("bigint", True),
    }
    column_rows = conn.execute(
        """SELECT a.attname, pg_catalog.format_type(a.atttypid, a.atttypmod), a.attnotnull
           FROM pg_catalog.pg_attribute a
           WHERE a.attrelid = %s AND a.attnum > 0 AND NOT a.attisdropped""",
        (table[0],),
    ).fetchall()
    columns = {row[0]: (row[1], row[2]) for row in column_rows}
    if columns != expected_columns:
        raise RuntimeError("managed_uploads columns differ from the approved schema")

    defaults = dict(conn.execute(
        """SELECT a.attname, pg_catalog.pg_get_expr(d.adbin, d.adrelid)
           FROM pg_catalog.pg_attribute a
           JOIN pg_catalog.pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
           WHERE a.attrelid = %s AND a.attname IN (
               'parser_metadata', 'uploaded_at', 'updated_at', 'row_version'
           )""",
        (table[0],),
    ).fetchall())
    if defaults != {
        "parser_metadata": "'{}'::jsonb", "uploaded_at": "now()",
        "updated_at": "now()", "row_version": "1",
    }:
        raise RuntimeError("managed_uploads defaults differ from the approved schema")

    constraints = {
        row[0]: (row[1], _normalize_catalog_sql(row[2]))
        for row in conn.execute(
            """SELECT conname, contype, pg_catalog.pg_get_constraintdef(oid)
               FROM pg_catalog.pg_constraint WHERE conrelid = %s""",
            (table[0],),
        ).fetchall()
    }
    expected_constraint_names = {
        "managed_uploads_pkey", "managed_uploads_doc_id_key",
        "managed_uploads_source_id_key", "managed_uploads_doc_fk",
        "managed_uploads_source_doc_fk", "managed_uploads_filename_check",
        "managed_uploads_format_check", "managed_uploads_title_check",
        "managed_uploads_file_size_check", "managed_uploads_strategy_check",
        "managed_uploads_metadata_check", "managed_uploads_row_version_check",
    }
    if set(constraints) != expected_constraint_names:
        raise RuntimeError("managed_uploads constraints differ from the approved schema")
    expected_definitions = {
        "managed_uploads_pkey": ("p", "primary key(upload_id)"),
        "managed_uploads_doc_id_key": ("u", "unique(doc_id)"),
        "managed_uploads_source_id_key": ("u", "unique(source_id)"),
        "managed_uploads_doc_fk": (
            "f", "foreign key(doc_id) references documents(doc_id) on delete restrict",
        ),
        "managed_uploads_source_doc_fk": (
            "f", "foreign key(source_id,doc_id) references document_sources(source_id,doc_id) on delete restrict",
        ),
    }
    for name, (kind, fragment) in expected_definitions.items():
        actual_kind, definition = constraints[name]
        if actual_kind != kind or _normalize_catalog_sql(fragment) not in definition:
            raise RuntimeError(f"managed_uploads constraint {name} is incompatible")
    check_terms = {
        "managed_uploads_filename_check": (
            "c", "char_length(original_filename)>=1", "char_length(original_filename)<=255",
        ),
        "managed_uploads_format_check": ("c", "file_format", "'pdf'", "'docx'", "'txt'", "'md'"),
        "managed_uploads_title_check": (
            "c", "char_length(title)>=1", "char_length(title)<=300",
        ),
        "managed_uploads_file_size_check": (
            "c", "file_size_bytes>=1", "file_size_bytes<=5242880",
        ),
        "managed_uploads_strategy_check": ("c", "chunking_strategy", "'paragraph'", "'fixed_overlap'"),
        "managed_uploads_metadata_check": ("c", "jsonb_typeof(parser_metadata)", "'object'"),
        "managed_uploads_row_version_check": ("c", "row_version", "1"),
    }
    for name, terms in check_terms.items():
        kind, definition = constraints[name]
        if kind != terms[0] or any(
            _normalize_catalog_sql(term) not in definition for term in terms[1:]
        ):
            raise RuntimeError(f"managed_uploads constraint {name} is incompatible")
    exact_check_literals = {
        "managed_uploads_format_check": ["pdf", "docx", "txt", "md"],
        "managed_uploads_strategy_check": ["paragraph", "fixed_overlap"],
        "managed_uploads_metadata_check": ["object"],
    }
    for name, expected_literals in exact_check_literals.items():
        actual_literals = re.findall(r"'([^']*)'", constraints[name][1])
        if actual_literals != expected_literals:
            raise RuntimeError(f"managed_uploads constraint {name} is incompatible")

    indexes = {
        row[0]: (row[1], row[2], row[3], _normalize_catalog_sql(row[4]))
        for row in conn.execute(
            """SELECT idx.relname, am.amname, i.indisunique, i.indisvalid,
                      pg_catalog.pg_get_indexdef(i.indexrelid)
               FROM pg_catalog.pg_index i
               JOIN pg_catalog.pg_class idx ON idx.oid = i.indexrelid
               JOIN pg_catalog.pg_am am ON am.oid = idx.relam
               WHERE i.indrelid = %s""",
            (table[0],),
        ).fetchall()
    }
    if set(indexes) != {
        "managed_uploads_pkey", "managed_uploads_doc_id_key",
        "managed_uploads_source_id_key", "managed_uploads_uploaded_at_idx",
    }:
        raise RuntimeError("managed_uploads indexes differ from the approved schema")
    list_index = indexes["managed_uploads_uploaded_at_idx"]
    if list_index[:3] != ("btree", False, True) or "uploaded_atdesc,upload_id" not in list_index[3]:
        raise RuntimeError("managed_uploads listing index is missing or incompatible")

    source_indexes = {
        row[0] for row in conn.execute(
            """SELECT idx.relname::text
               FROM pg_catalog.pg_index i
               JOIN pg_catalog.pg_class idx ON idx.oid = i.indexrelid
               WHERE i.indrelid = 'public.document_sources'::regclass""",
        ).fetchall()
    }
    if source_indexes != {
        "document_sources_pkey", "document_sources_doc_id_idx",
        "document_sources_title_normalized_idx", "document_sources_source_doc_idx",
    }:
        raise RuntimeError("document_sources indexes include unexpected schema objects")

    source_pair_index = conn.execute(
        """SELECT am.amname, i.indisunique, i.indisvalid,
                  pg_catalog.pg_get_indexdef(i.indexrelid)
           FROM pg_catalog.pg_index i
           JOIN pg_catalog.pg_class idx ON idx.oid = i.indexrelid
           JOIN pg_catalog.pg_am am ON am.oid = idx.relam
           WHERE idx.oid = to_regclass('public.document_sources_source_doc_idx')
             AND i.indrelid = 'public.document_sources'::regclass"""
    ).fetchone()
    if (not source_pair_index or source_pair_index[:3] != ("btree", True, True)
            or "source_id,doc_id" not in _normalize_catalog_sql(source_pair_index[3])):
        raise RuntimeError("the approved source/document pair index is missing or incompatible")

    if require_empty and conn.execute(
        "SELECT EXISTS (SELECT 1 FROM public.managed_uploads LIMIT 1)"
    ).fetchone()[0]:
        raise RuntimeError(
            "managed_uploads is non-empty; legacy corpus ingestion must not run "
            "after managed uploads begin"
        )
    return True


def _normalize_catalog_sql(value: str) -> str:
    """Normalize catalog SQL for stable, case-insensitive schema checks."""
    return re.sub(r"\s+", "", value.lower().replace('"', "")).replace("public.", "")


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
            "chunking_strategy": "text", "start_char": "integer", "end_char": "integer",
            "embedding": "halfvec(384)",
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
            type_matches = (actual_type.endswith("halfvec(384)") if expected_type == "halfvec(384)"
                            else actual_type == expected_type)
            if not type_matches:
                raise RuntimeError(f"public.{table} has an incompatible {column} column; refusing schema changes")
        if table == "chunks" and "chunk_text" in columns[table]:
            raise RuntimeError("public.chunks still has duplicate chunk_text; refusing schema changes")


def read_database_metrics(conn: Connection) -> dict[str, Any]:
    """Measure corpus and approved upload-table storage without mixing counts."""
    database_size = conn.execute("SELECT pg_database_size(current_database())").fetchone()[0]
    tables: dict[str, dict[str, int]] = {}
    additional_tables: dict[str, dict[str, int]] = {}
    indexes: list[dict[str, Any]] = []
    for table in (*TARGET_TABLES, MANAGED_UPLOADS_TABLE):
        relation = conn.execute("SELECT to_regclass(%s)", (f"public.{table}",)).fetchone()[0]
        metric_group = tables if table in TARGET_TABLES else additional_tables
        if relation is None:
            metric_group[table] = {
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
        metric_group[table] = {
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
        "additional_tables": additional_tables,
        "indexes": indexes,
        "embedding_storage": {
            "rows": embedding_rows,
            "value_bytes_total": embedding_bytes,
            "value_bytes_average": round(float(average_embedding_bytes), 2),
            "note": "pg_column_size of halfvec values; excludes chunk row overhead and HNSW index",
        },
    }


def read_database_document_ids(conn: Connection) -> set[str]:
    """Return current document IDs, or an empty set before the table is created."""
    relation = conn.execute("SELECT to_regclass('public.documents')").fetchone()[0]
    if relation is None:
        return set()
    return {row[0] for row in conn.execute("SELECT doc_id FROM public.documents").fetchall()}


def read_indexed_source_evidence(conn: Connection) -> list[dict[str, Any]]:
    """Read source evidence with its indexed paragraph text for coverage gating."""
    return [
        {"source_id": row[0], "title_normalized": row[1], "sentences": row[2], "chunk_text": row[3]}
        for row in conn.execute(
            """SELECT s.source_id, s.title_normalized, s.sentences,
                      substring(d.full_text FROM c.start_char + 1 FOR c.end_char - c.start_char)
               FROM public.document_sources s
               JOIN public.chunks c ON c.doc_id = s.doc_id
                                    AND c.chunking_strategy = 'paragraph'
               JOIN public.documents d ON d.doc_id = c.doc_id
               ORDER BY s.source_id, c.chunk_position, c.chunk_id"""
        ).fetchall()
    ]


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
                "chunk_id", "doc_id", "chunk_position", "chunking_strategy",
                "start_char", "end_char", "chunk_text", "embedding", "embedding_model",
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
    fields = ("chunk_id", "doc_id", "chunk_position", "chunking_strategy",
              "start_char", "end_char", "chunk_text", "embedding_model")
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
    invalid_offsets = conn.execute(
        """SELECT count(*) FROM public.chunks c
           JOIN public.documents d ON d.doc_id = c.doc_id
           WHERE c.doc_id = ANY(%s)
             AND (c.end_char > char_length(d.full_text)
                  OR char_length(substring(d.full_text FROM c.start_char + 1
                                           FOR c.end_char - c.start_char)) <> c.end_char - c.start_char)""",
        (list(doc_ids),),
    ).fetchone()[0]
    total_documents = conn.execute("SELECT count(*) FROM public.documents").fetchone()[0]
    total_sources = conn.execute("SELECT count(*) FROM public.document_sources").fetchone()[0]
    total_chunks = conn.execute("SELECT count(*) FROM public.chunks").fetchone()[0]
    return {
        "target_documents": target_docs,
        "target_sources": source_count,
        "target_chunks": chunk_count,
        "orphan_target_chunks": orphan_count,
        "orphan_target_sources": orphan_source_count,
        "wrong_dimension_target_embeddings": wrong_dimensions,
        "invalid_target_chunk_offsets": invalid_offsets,
        "total_documents": total_documents,
        "total_sources": total_sources,
        "total_chunks": total_chunks,
    }


def build_hnsw_index_after_bulk_load(
    conn: Connection,
    *,
    expected_documents: int,
    expected_sources: int,
    expected_chunks: int,
) -> float:
    """Build the halfvec HNSW index only after the verified 1K bulk load."""
    import time

    if expected_documents != 1_000:
        raise ValueError("the Phase 1E HNSW build is restricted to exactly 1,000 documents")
    actual = conn.execute(
        """SELECT (SELECT count(*) FROM public.documents),
                  (SELECT count(*) FROM public.document_sources),
                  (SELECT count(*) FROM public.chunks)"""
    ).fetchone()
    if actual != (expected_documents, expected_sources, expected_chunks):
        raise RuntimeError("refusing HNSW build before the exact bulk corpus is loaded")
    started = time.perf_counter()
    conn.execute(
        """CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw_idx
           ON public.chunks USING hnsw
           (embedding extensions.halfvec_cosine_ops)"""
    )
    conn.execute("ANALYZE public.documents")
    conn.execute("ANALYZE public.document_sources")
    conn.execute("ANALYZE public.chunks")
    return time.perf_counter() - started


_RETRIEVAL_FILTER_COLUMNS = {
    "chunking_strategy": "chunking_strategy",
    "embedding_model": "embedding_model",
}


def _retrieval_filter_sql(filters: Mapping[str, str] | None) -> tuple[sql.Composable, list[str]]:
    """Build a small filter whitelist using SQL identifiers and bound values."""
    if filters is None:
        return sql.SQL("TRUE"), []
    if not isinstance(filters, Mapping):
        raise TypeError("retrieval filters must be a mapping")

    clauses: list[sql.Composable] = []
    values: list[str] = []
    for key in sorted(filters):
        value = filters[key]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"retrieval filter {key!r} must be a non-empty string")
        if key == "source_split":
            clauses.append(sql.SQL(
                "EXISTS (SELECT 1 FROM public.document_sources sf "
                "WHERE sf.doc_id = c.doc_id AND sf.source_split = %s)"
            ))
        elif key in _RETRIEVAL_FILTER_COLUMNS:
            clauses.append(sql.SQL("c.{} = %s").format(
                sql.Identifier(_RETRIEVAL_FILTER_COLUMNS[key]),
            ))
        else:
            raise ValueError(f"unsupported retrieval filter: {key}")
        values.append(value)
    return sql.SQL(" AND ").join(clauses) if clauses else sql.SQL("TRUE"), values


def _search_result_rows(rows: Sequence[tuple[Any, ...]], score_name: str) -> list[dict[str, Any]]:
    """Map a parameterized retrieval query row to stable, source-aware hit data."""
    return [{
        "chunk_id": row[0],
        "doc_id": row[1],
        "chunk_position": row[2],
        "chunk_text": row[3],
        "metadata": row[4],
        "sources": row[5] or [],
        score_name: float(row[6]),
        **({"validation_source": {
            "full_text": row[7], "start_char": row[8], "end_char": row[9],
        }} if len(row) > 7 else {}),
    } for row in rows]


def semantic_search_chunks(
    conn: Connection,
    vector: Sequence[float],
    *,
    limit: int = 10,
    filters: Mapping[str, str] | None = None,
    include_validation_source: bool = False,
) -> list[dict[str, Any]]:
    """Run pgvector cosine retrieval and include paragraph titles and provenance."""
    if len(vector) != 384 or not all(math.isfinite(float(value)) for value in vector):
        raise ValueError("query embedding must contain 384 finite values")
    if not 1 <= limit <= 100:
        raise ValueError("retrieval limit must be between 1 and 100")
    filter_sql, filter_values = _retrieval_filter_sql(filters)
    validation_fields = sql.SQL(", d.full_text, c.start_char, c.end_char") if include_validation_source else sql.SQL("")
    literal = "[" + ",".join(format(float(value), ".9g") for value in vector) + "]"
    statement = sql.SQL(
        """WITH query_vector AS (
               SELECT %s::extensions.halfvec(384) AS embedding
           )
           SELECT c.chunk_id, c.doc_id, c.chunk_position,
                  substring(d.full_text FROM c.start_char + 1 FOR c.end_char - c.start_char), d.metadata,
                  COALESCE(p.sources, '[]'::jsonb) AS sources,
                  c.embedding OPERATOR(extensions.<=>) q.embedding AS cosine_distance{}
           FROM public.chunks c
           JOIN public.documents d ON d.doc_id = c.doc_id
           CROSS JOIN query_vector q
           LEFT JOIN LATERAL (
               SELECT jsonb_agg(jsonb_build_object(
                          'source_id', s.source_id,
                          'title_alias', s.title_alias,
                          'source_url', s.source_url,
                          'source_revision', s.source_revision,
                          'source_split', s.source_split
                      ) ORDER BY s.title_normalized, s.source_id) AS sources
               FROM public.document_sources s WHERE s.doc_id = c.doc_id
           ) p ON TRUE
           WHERE {}
           ORDER BY c.embedding OPERATOR(extensions.<=>) q.embedding, c.chunk_id
           LIMIT %s"""
    ).format(validation_fields, filter_sql)
    rows = conn.execute(statement, (literal, *filter_values, limit)).fetchall()
    return _search_result_rows(rows, "cosine_distance")


def keyword_search_chunks(
    conn: Connection,
    query: str,
    *,
    limit: int = 10,
    filters: Mapping[str, str] | None = None,
    include_validation_source: bool = False,
    strategy: str = "or",
    common_term_threshold: float = 0.05,
) -> list[dict[str, Any]]:
    """Run English OR FTS, optionally filtering only corpus-common query terms."""
    if not isinstance(query, str):
        raise ValueError("search query must be a string")
    if not 1 <= limit <= 100:
        raise ValueError("retrieval limit must be between 1 and 100")
    if strategy not in {"or", "informative"}:
        raise ValueError("keyword strategy must be 'or' or 'informative'")
    try:
        common_term_threshold = float(common_term_threshold)
    except (TypeError, ValueError):
        raise ValueError("common-term threshold must be between 0 and 1") from None
    if not math.isfinite(common_term_threshold) or not 0 <= common_term_threshold <= 1:
        raise ValueError("common-term threshold must be between 0 and 1")
    if not query.strip():
        return []
    filter_sql, filter_values = _retrieval_filter_sql(filters)
    validation_fields = sql.SQL(", d.full_text, c.start_char, c.end_char") if include_validation_source else sql.SQL("")
    if strategy == "or":
        term_ctes = sql.SQL(
            """input_lexemes AS (
                   SELECT unnest(
                       tsvector_to_array(to_tsvector('english'::regconfig, %s))
                   ) AS lexeme
               ), query_terms AS (
                   SELECT row_number() OVER (ORDER BY lexeme)::integer AS term_number,
                          plainto_tsquery('english'::regconfig, lexeme) AS term_query
                   FROM input_lexemes
               )"""
        )
        term_values: tuple[Any, ...] = (query,)
    else:
        from app.retrieval.keywords import protected_query_text

        term_ctes = sql.SQL(
            """fts_statistics AS MATERIALIZED (
                   SELECT array_to_json(most_common_elems) AS common_lexemes,
                          array_to_json(most_common_elem_freqs) AS common_frequencies
                   FROM pg_stats
                   WHERE schemaname = 'public' AND tablename = 'chunks' AND attname = 'tsv'
               ), common_term_frequencies AS MATERIALIZED (
                   SELECT term.value AS lexeme,
                          frequency.value::double precision AS document_frequency
                   FROM fts_statistics
                   CROSS JOIN LATERAL json_array_elements_text(common_lexemes)
                        WITH ORDINALITY AS term(value, term_position)
                   JOIN LATERAL json_array_elements_text(common_frequencies)
                        WITH ORDINALITY AS frequency(value, term_position) USING (term_position)
               ), input_lexemes AS (
                   SELECT unnest(
                       tsvector_to_array(to_tsvector('english'::regconfig, %s))
                   ) AS lexeme
               ), protected_lexemes AS (
                   SELECT unnest(
                       tsvector_to_array(to_tsvector('english'::regconfig, %s))
                   ) AS lexeme
               ), classified_lexemes AS (
                   SELECT input.lexeme,
                          EXISTS (
                              SELECT 1 FROM protected_lexemes AS protected
                              WHERE protected.lexeme = input.lexeme
                          ) AS is_protected,
                          COALESCE(common.document_frequency, 0.0) AS document_frequency
                   FROM input_lexemes AS input
                   LEFT JOIN common_term_frequencies AS common USING (lexeme)
               ), retained_lexemes AS MATERIALIZED (
                   SELECT lexeme FROM classified_lexemes
                   WHERE is_protected OR document_frequency < %s
               ), selected_lexemes AS (
                   SELECT lexeme FROM retained_lexemes
                   UNION ALL
                   SELECT input.lexeme FROM input_lexemes AS input
                   WHERE NOT EXISTS (SELECT 1 FROM retained_lexemes)
               ), query_terms AS (
                   SELECT row_number() OVER (ORDER BY lexeme)::integer AS term_number,
                          plainto_tsquery('english'::regconfig, lexeme) AS term_query
                   FROM selected_lexemes
               )"""
        )
        term_values = (query, protected_query_text(query), common_term_threshold)
    statement = sql.SQL(
        """WITH RECURSIVE {}, query_fold(term_number, tsquery) AS (
               SELECT term_number, term_query
               FROM query_terms WHERE term_number = 1
               UNION ALL
               SELECT query_terms.term_number, query_fold.tsquery || query_terms.term_query
               FROM query_fold
               JOIN query_terms
                 ON query_terms.term_number = query_fold.term_number + 1
           ), search_query AS (
               SELECT tsquery FROM query_fold
               ORDER BY term_number DESC LIMIT 1
           )
           SELECT c.chunk_id, c.doc_id, c.chunk_position,
                  substring(d.full_text FROM c.start_char + 1 FOR c.end_char - c.start_char), d.metadata,
                  COALESCE(p.sources, '[]'::jsonb) AS sources,
                  ts_rank_cd(c.tsv, q.tsquery) AS keyword_score{}
           FROM public.chunks c
           JOIN public.documents d ON d.doc_id = c.doc_id
           CROSS JOIN search_query q
           LEFT JOIN LATERAL (
               SELECT jsonb_agg(jsonb_build_object(
                          'source_id', s.source_id,
                          'title_alias', s.title_alias,
                          'source_url', s.source_url,
                          'source_revision', s.source_revision,
                          'source_split', s.source_split
                      ) ORDER BY s.title_normalized, s.source_id) AS sources
               FROM public.document_sources s WHERE s.doc_id = c.doc_id
           ) p ON TRUE
           WHERE c.tsv @@ q.tsquery AND {}
           ORDER BY keyword_score DESC, c.chunk_id
           LIMIT %s"""
    ).format(term_ctes, validation_fields, filter_sql)
    rows = conn.execute(statement, (*term_values, *filter_values, limit)).fetchall()
    return _search_result_rows(rows, "keyword_score")


def read_document_context(conn: Connection, doc_id: str) -> dict[str, Any] | None:
    """Read one canonical document and all its provenance without changing data."""
    row = conn.execute(
        """SELECT d.doc_id, d.full_text, d.metadata,
                  COALESCE(jsonb_agg(jsonb_build_object(
                      'source_id', s.source_id, 'title_alias', s.title_alias,
                      'title_normalized', s.title_normalized, 'source_url', s.source_url,
                      'source_revision', s.source_revision, 'source_split', s.source_split,
                      'sentences', s.sentences
                  ) ORDER BY s.title_normalized, s.source_id)
                    FILTER (WHERE s.source_id IS NOT NULL), '[]'::jsonb) AS sources
           FROM public.documents d
           LEFT JOIN public.document_sources s ON s.doc_id = d.doc_id
           WHERE d.doc_id = %s
           GROUP BY d.doc_id""",
        (doc_id,),
    ).fetchone()
    if row is None:
        return None
    return {"doc_id": row[0], "full_text": row[1], "metadata": row[2], "sources": row[3] or []}


def cosine_search(conn: Connection, vector: Sequence[float], limit: int = 5) -> list[dict[str, Any]]:
    """Run a real PostgreSQL pgvector cosine-distance query in ascending rank order."""
    literal = "[" + ",".join(format(float(value), ".9g") for value in vector) + "]"
    rows = conn.execute(
        """WITH query_vector AS (SELECT %s::extensions.halfvec(384) AS embedding)
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
