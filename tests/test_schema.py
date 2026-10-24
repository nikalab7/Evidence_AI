from pathlib import Path


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
