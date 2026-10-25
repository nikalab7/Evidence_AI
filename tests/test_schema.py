from pathlib import Path

import pytest

from app.db.queries import (
    apply_schema,
    validate_approved_public_relations,
    verify_managed_uploads_schema,
)

SCHEMA = Path("migrations/schema.sql").read_text(encoding="utf-8")


def test_optimized_schema_keeps_one_document_text_copy_and_halfvec_offsets():
    assert "full_text text NOT NULL" in SCHEMA
    assert "start_char integer NOT NULL" in SCHEMA
    assert "end_char integer NOT NULL" in SCHEMA
    assert "embedding extensions.halfvec(384) NOT NULL" in SCHEMA
    assert "chunk_text text" not in SCHEMA
    assert "CREATE INDEX IF NOT EXISTS chunks_tsv_gin_idx" in SCHEMA
    assert "USING hnsw" not in SCHEMA


def test_search_vector_weights_all_title_aliases_and_chunk_body_and_refreshes():
    assert "string_agg(s.title_alias" in SCHEMA
    assert "setweight(to_tsvector('english'::regconfig, COALESCE(alias_text, '')), 'A')" in SCHEMA
    assert "), 'B')" in SCHEMA
    assert "evidenceai_sources_refresh_fts" in SCHEMA
    assert "evidenceai_documents_refresh_fts" in SCHEMA
    assert "SET tsv = c.tsv" in SCHEMA


def test_schema_has_no_destructive_table_operations_and_blocks_public_roles():
    lowered = SCHEMA.lower()
    assert "drop table" not in lowered
    assert "truncate " not in lowered
    assert "delete from " not in lowered
    assert "enable row level security" in lowered
    assert "from public, anon, authenticated" in lowered
    assert "to service_role" in lowered


def test_public_relation_allowlist_accepts_only_phase1e_and_managed_upload_tables():
    assert validate_approved_public_relations({"documents", "document_sources", "chunks"}) is False
    assert validate_approved_public_relations({
        "documents", "document_sources", "chunks", "managed_uploads",
    }) is True
    with pytest.raises(RuntimeError, match="unexpected tables"):
        validate_approved_public_relations({
            "documents", "document_sources", "chunks", "managed_uploads", "billing_data",
        })


class _Result:
    def __init__(self, rows):
        self.rows = list(rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class _ManagedSchemaFixture:
    columns = {
        "upload_id": ("uuid", True), "doc_id": ("text", True),
        "source_id": ("text", True), "original_filename": ("text", True),
        "file_format": ("text", True), "title": ("text", True),
        "file_size_bytes": ("integer", True), "chunking_strategy": ("text", True),
        "parser_metadata": ("jsonb", True),
        "uploaded_at": ("timestamp with time zone", True),
        "updated_at": ("timestamp with time zone", True), "row_version": ("bigint", True),
    }
    constraints = [
        ("managed_uploads_pkey", "p", "PRIMARY KEY (upload_id)"),
        ("managed_uploads_doc_id_key", "u", "UNIQUE (doc_id)"),
        ("managed_uploads_source_id_key", "u", "UNIQUE (source_id)"),
        ("managed_uploads_doc_fk", "f", "FOREIGN KEY (doc_id) REFERENCES documents(doc_id) ON DELETE RESTRICT"),
        ("managed_uploads_source_doc_fk", "f", "FOREIGN KEY (source_id, doc_id) REFERENCES document_sources(source_id, doc_id) ON DELETE RESTRICT"),
        ("managed_uploads_filename_check", "c", "CHECK (char_length(original_filename) >= 1 AND char_length(original_filename) <= 255)"),
        ("managed_uploads_format_check", "c", "CHECK (file_format = ANY (ARRAY['pdf'::text, 'docx'::text, 'txt'::text, 'md'::text]))"),
        ("managed_uploads_title_check", "c", "CHECK (char_length(title) >= 1 AND char_length(title) <= 300)"),
        ("managed_uploads_file_size_check", "c", "CHECK (file_size_bytes >= 1 AND file_size_bytes <= 5242880)"),
        ("managed_uploads_strategy_check", "c", "CHECK (chunking_strategy = ANY (ARRAY['paragraph'::text, 'fixed_overlap'::text]))"),
        ("managed_uploads_metadata_check", "c", "CHECK (jsonb_typeof(parser_metadata) = 'object'::text)"),
        ("managed_uploads_row_version_check", "c", "CHECK (row_version >= 1)"),
    ]

    def __init__(self, *, mismatch_source_fk=False, extra_source_index=False, nonempty=False):
        self.mismatch_source_fk = mismatch_source_fk
        self.extra_source_index = extra_source_index
        self.nonempty = nonempty

    def execute(self, query, params=()):
        statement = " ".join(str(query).lower().split())
        if "select table_type from information_schema.tables" in statement:
            return _Result([("BASE TABLE",)])
        if "has_table_privilege('anon'" in statement and "from pg_catalog.pg_class c" in statement:
            return _Result([(42, "r", True, *([False] * 8), *([True] * 4))])
        if "aclexplode" in statement:
            return _Result([])
        if "from pg_catalog.pg_policy" in statement:
            return _Result([])
        if "from pg_catalog.pg_trigger" in statement:
            return _Result([])
        if "from pg_catalog.pg_attribute a join pg_catalog.pg_attrdef" in statement:
            return _Result([
                ("parser_metadata", "'{}'::jsonb"), ("uploaded_at", "now()"),
                ("updated_at", "now()"), ("row_version", "1"),
            ])
        if "from pg_catalog.pg_attribute a" in statement:
            return _Result([
                (name, type_name, not_null)
                for name, (type_name, not_null) in self.columns.items()
            ])
        if "pg_get_constraintdef(oid)" in statement:
            rows = list(self.constraints)
            if self.mismatch_source_fk:
                rows = [
                    (name, kind, definition.replace("source_id, doc_id", "source_id"))
                    if name == "managed_uploads_source_doc_fk" else (name, kind, definition)
                    for name, kind, definition in rows
                ]
            return _Result(rows)
        if "where i.indrelid = %s" in statement:
            return _Result([
                ("managed_uploads_pkey", "btree", True, True, "CREATE UNIQUE INDEX managed_uploads_pkey ON public.managed_uploads USING btree (upload_id)"),
                ("managed_uploads_doc_id_key", "btree", True, True, "CREATE UNIQUE INDEX managed_uploads_doc_id_key ON public.managed_uploads USING btree (doc_id)"),
                ("managed_uploads_source_id_key", "btree", True, True, "CREATE UNIQUE INDEX managed_uploads_source_id_key ON public.managed_uploads USING btree (source_id)"),
                ("managed_uploads_uploaded_at_idx", "btree", False, True, "CREATE INDEX managed_uploads_uploaded_at_idx ON public.managed_uploads USING btree (uploaded_at DESC, upload_id)"),
            ])
        if "where i.indrelid = 'public.document_sources'::regclass" in statement:
            names = [
                "document_sources_doc_id_idx", "document_sources_pkey",
                "document_sources_source_doc_idx", "document_sources_title_normalized_idx",
            ]
            if self.extra_source_index:
                names.append("unapproved_document_sources_idx")
            return _Result([(name,) for name in names])
        if "to_regclass('public.document_sources_source_doc_idx')" in statement:
            return _Result([("btree", True, True, "CREATE UNIQUE INDEX document_sources_source_doc_idx ON public.document_sources USING btree (source_id, doc_id)")])
        if "select exists (select 1 from public.managed_uploads" in statement:
            return _Result([(self.nonempty,)])
        raise AssertionError(f"unexpected schema verification SQL: {statement[:100]}")


def test_managed_schema_guard_checks_ownership_security_and_empty_legacy_gate():
    assert verify_managed_uploads_schema(_ManagedSchemaFixture(), require_empty=True) is True
    with pytest.raises(RuntimeError, match="source_doc_fk"):
        verify_managed_uploads_schema(
            _ManagedSchemaFixture(mismatch_source_fk=True), require_empty=True,
        )
    with pytest.raises(RuntimeError, match="legacy corpus ingestion"):
        verify_managed_uploads_schema(
            _ManagedSchemaFixture(nonempty=True), require_empty=True,
        )
    with pytest.raises(RuntimeError, match="document_sources indexes"):
        verify_managed_uploads_schema(
            _ManagedSchemaFixture(extra_source_index=True), require_empty=False,
        )


def test_legacy_schema_writer_aborts_before_ddl_if_uploads_exist():
    class ConnectionFixture:
        def __init__(self):
            self.catalog = _ManagedSchemaFixture(nonempty=True)
            self.schema_was_executed = False

        def execute(self, query, params=()):
            statement = " ".join(str(query).lower().split())
            if "select table_name from information_schema.tables" in statement:
                return _Result([
                    ("documents",), ("document_sources",), ("chunks",), ("managed_uploads",),
                ])
            if statement == "test additive schema statement":
                self.schema_was_executed = True
                return _Result()
            return self.catalog.execute(query, params)

    conn = ConnectionFixture()
    with pytest.raises(RuntimeError, match="legacy corpus ingestion"):
        apply_schema(conn, "TEST ADDITIVE SCHEMA STATEMENT")
    assert conn.schema_was_executed is False
