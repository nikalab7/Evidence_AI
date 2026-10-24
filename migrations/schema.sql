-- Additive Phase 1C schema. This migration never drops or updates existing rows.
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions;

CREATE TABLE IF NOT EXISTS public.documents (
    doc_id text PRIMARY KEY CHECK (doc_id ~ '^[0-9a-f]{64}$'),
    content_hash text NOT NULL UNIQUE CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    full_text text NOT NULL,
    metadata jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (doc_id = content_hash)
);

CREATE TABLE IF NOT EXISTS public.document_sources (
    source_id text PRIMARY KEY CHECK (source_id ~ '^[0-9a-f]{64}$'),
    doc_id text NOT NULL REFERENCES public.documents(doc_id) ON DELETE CASCADE,
    title_alias text NOT NULL,
    title_normalized text NOT NULL,
    source_url text NOT NULL,
    source_revision text NOT NULL,
    source_split text NOT NULL,
    sentences jsonb NOT NULL CHECK (jsonb_typeof(sentences) = 'array'),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.chunks (
    chunk_id text PRIMARY KEY CHECK (chunk_id ~ '^[0-9a-f]{64}$'),
    doc_id text NOT NULL REFERENCES public.documents(doc_id) ON DELETE CASCADE,
    chunk_position integer NOT NULL CHECK (chunk_position >= 0),
    chunking_strategy text NOT NULL,
    chunk_text text NOT NULL,
    embedding extensions.vector(384) NOT NULL,
    embedding_model text NOT NULL,
    tsv tsvector GENERATED ALWAYS AS (to_tsvector('english'::regconfig, chunk_text)) STORED,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (doc_id, chunking_strategy, chunk_position)
);

CREATE INDEX IF NOT EXISTS document_sources_doc_id_idx
    ON public.document_sources (doc_id);
CREATE INDEX IF NOT EXISTS document_sources_title_normalized_idx
    ON public.document_sources (title_normalized);
CREATE INDEX IF NOT EXISTS chunks_doc_id_idx ON public.chunks (doc_id);
CREATE INDEX IF NOT EXISTS chunks_tsv_gin_idx ON public.chunks USING gin (tsv);
CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw_idx
    ON public.chunks USING hnsw (embedding extensions.vector_cosine_ops);
