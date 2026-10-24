-- Phase 1E optimized schema. This file is additive and contains no DROP/DELETE.
CREATE SCHEMA IF NOT EXISTS extensions;
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions;

CREATE TABLE IF NOT EXISTS public.documents (
    doc_id text PRIMARY KEY CHECK (doc_id ~ '^[0-9a-f]{64}$'),
    content_hash text NOT NULL UNIQUE CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    full_text text NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
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
    start_char integer NOT NULL CHECK (start_char >= 0),
    end_char integer NOT NULL CHECK (end_char > start_char),
    embedding extensions.halfvec(384) NOT NULL,
    embedding_model text NOT NULL,
    tsv tsvector NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (doc_id, chunking_strategy, chunk_position)
);

CREATE INDEX IF NOT EXISTS document_sources_doc_id_idx
    ON public.document_sources (doc_id);
CREATE INDEX IF NOT EXISTS document_sources_title_normalized_idx
    ON public.document_sources (title_normalized);
CREATE INDEX IF NOT EXISTS chunks_doc_id_idx ON public.chunks (doc_id);
CREATE INDEX IF NOT EXISTS chunks_tsv_gin_idx ON public.chunks USING gin (tsv);

CREATE OR REPLACE FUNCTION public.evidenceai_set_chunk_tsv()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, extensions
AS $$
DECLARE
    document_text text;
    alias_text text;
BEGIN
    SELECT d.full_text INTO document_text
    FROM public.documents AS d
    WHERE d.doc_id = NEW.doc_id;
    IF document_text IS NULL THEN
        RAISE EXCEPTION 'chunk document % does not exist', NEW.doc_id;
    END IF;

    SELECT string_agg(s.title_alias, ' ' ORDER BY s.title_normalized, s.source_id)
    INTO alias_text
    FROM public.document_sources AS s
    WHERE s.doc_id = NEW.doc_id;

    NEW.tsv :=
        setweight(to_tsvector('english'::regconfig, COALESCE(alias_text, '')), 'A') ||
        setweight(to_tsvector(
            'english'::regconfig,
            substring(document_text FROM NEW.start_char + 1 FOR NEW.end_char - NEW.start_char)
        ), 'B');
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.evidenceai_refresh_document_fts(target_doc_id text)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, extensions
AS $$
BEGIN
    UPDATE public.chunks AS c
    SET tsv = c.tsv
    WHERE c.doc_id = target_doc_id;
END;
$$;

CREATE OR REPLACE FUNCTION public.evidenceai_source_changed()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, extensions
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        PERFORM public.evidenceai_refresh_document_fts(OLD.doc_id);
        RETURN OLD;
    END IF;
    IF TG_OP = 'UPDATE' AND OLD.doc_id IS DISTINCT FROM NEW.doc_id THEN
        PERFORM public.evidenceai_refresh_document_fts(OLD.doc_id);
    END IF;
    PERFORM public.evidenceai_refresh_document_fts(NEW.doc_id);
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.evidenceai_document_text_changed()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, extensions
AS $$
BEGIN
    IF OLD.full_text IS DISTINCT FROM NEW.full_text THEN
        PERFORM public.evidenceai_refresh_document_fts(NEW.doc_id);
    END IF;
    RETURN NEW;
END;
$$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgrelid = 'public.chunks'::regclass
                   AND tgname = 'evidenceai_chunks_set_tsv' AND NOT tgisinternal) THEN
        EXECUTE 'CREATE TRIGGER evidenceai_chunks_set_tsv
                 BEFORE INSERT OR UPDATE OF doc_id, start_char, end_char, tsv
                 ON public.chunks FOR EACH ROW
                 EXECUTE FUNCTION public.evidenceai_set_chunk_tsv()';
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgrelid = 'public.document_sources'::regclass
                   AND tgname = 'evidenceai_sources_refresh_fts' AND NOT tgisinternal) THEN
        EXECUTE 'CREATE TRIGGER evidenceai_sources_refresh_fts
                 AFTER INSERT OR UPDATE OR DELETE ON public.document_sources
                 FOR EACH ROW EXECUTE FUNCTION public.evidenceai_source_changed()';
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgrelid = 'public.documents'::regclass
                   AND tgname = 'evidenceai_documents_refresh_fts' AND NOT tgisinternal) THEN
        EXECUTE 'CREATE TRIGGER evidenceai_documents_refresh_fts
                 AFTER UPDATE OF full_text ON public.documents
                 FOR EACH ROW EXECUTE FUNCTION public.evidenceai_document_text_changed()';
    END IF;
END $$;

ALTER TABLE public.documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.document_sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chunks ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.documents, public.document_sources, public.chunks
    FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE
    public.documents, public.document_sources, public.chunks TO service_role;
GRANT USAGE ON SCHEMA public, extensions TO service_role;
REVOKE ALL ON FUNCTION public.evidenceai_set_chunk_tsv() FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.evidenceai_refresh_document_fts(text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.evidenceai_source_changed() FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.evidenceai_document_text_changed() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.evidenceai_set_chunk_tsv() TO service_role;
GRANT EXECUTE ON FUNCTION public.evidenceai_refresh_document_fts(text) TO service_role;
GRANT EXECUTE ON FUNCTION public.evidenceai_source_changed() TO service_role;
GRANT EXECUTE ON FUNCTION public.evidenceai_document_text_changed() TO service_role;
