-- PROPOSAL ONLY — do not run without explicit owner approval.
-- Additive ownership metadata for EvidenceAI uploads. Never removes or edits
-- existing corpus rows. Reapplication is safe and validates any pre-existing
-- object instead of silently accepting an incompatible table/index.

-- PostgreSQL requires a unique referenced key for the paired source/document
-- foreign key. source_id is already unique; this index enforces the exact pair.
CREATE UNIQUE INDEX IF NOT EXISTS document_sources_source_doc_idx
    ON public.document_sources (source_id, doc_id);

CREATE TABLE IF NOT EXISTS public.managed_uploads (
    upload_id uuid CONSTRAINT managed_uploads_pkey PRIMARY KEY,
    doc_id text NOT NULL CONSTRAINT managed_uploads_doc_id_key UNIQUE
        CONSTRAINT managed_uploads_doc_fk
        REFERENCES public.documents(doc_id) ON DELETE RESTRICT,
    source_id text NOT NULL CONSTRAINT managed_uploads_source_id_key UNIQUE,
    original_filename text NOT NULL
        CONSTRAINT managed_uploads_filename_check
        CHECK (char_length(original_filename) >= 1 AND char_length(original_filename) <= 255),
    file_format text NOT NULL
        CONSTRAINT managed_uploads_format_check
        CHECK (file_format IN ('pdf', 'docx', 'txt', 'md')),
    title text NOT NULL
        CONSTRAINT managed_uploads_title_check
        CHECK (char_length(title) >= 1 AND char_length(title) <= 300),
    file_size_bytes integer NOT NULL
        CONSTRAINT managed_uploads_file_size_check
        CHECK (file_size_bytes >= 1 AND file_size_bytes <= 5242880),
    chunking_strategy text NOT NULL
        CONSTRAINT managed_uploads_strategy_check
        CHECK (chunking_strategy IN ('paragraph', 'fixed_overlap')),
    parser_metadata jsonb NOT NULL DEFAULT '{}'::jsonb
        CONSTRAINT managed_uploads_metadata_check
        CHECK (jsonb_typeof(parser_metadata) = 'object'),
    uploaded_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    row_version bigint NOT NULL DEFAULT 1
        CONSTRAINT managed_uploads_row_version_check CHECK (row_version >= 1),
    CONSTRAINT managed_uploads_source_doc_fk
        FOREIGN KEY (source_id, doc_id)
        REFERENCES public.document_sources(source_id, doc_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS managed_uploads_uploaded_at_idx
    ON public.managed_uploads (uploaded_at DESC, upload_id);

ALTER TABLE public.managed_uploads ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.managed_uploads FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.managed_uploads TO service_role;
GRANT USAGE ON SCHEMA public TO service_role;

-- Fail closed if IF NOT EXISTS encountered a same-named but incompatible object.
DO $$
DECLARE
    actual_columns text[];
    actual_constraints text[];
    actual_indexes text[];
    actual_source_indexes text[];
    managed_table oid := to_regclass('public.managed_uploads');
    source_pair_index oid := to_regclass('public.document_sources_source_doc_idx');
BEGIN
    IF managed_table IS NULL OR NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_class
        WHERE oid = managed_table AND relkind = 'r' AND relrowsecurity
    ) THEN
        RAISE EXCEPTION 'managed_uploads must be a base table with RLS enabled';
    END IF;

    SELECT array_agg(
               a.attname::text || ':' || pg_catalog.format_type(a.atttypid, a.atttypmod)
                   || ':' || CASE WHEN a.attnotnull THEN 'not_null' ELSE 'nullable' END
                     ORDER BY a.attnum)
      INTO actual_columns
      FROM pg_catalog.pg_attribute AS a
     WHERE a.attrelid = managed_table AND a.attnum > 0 AND NOT a.attisdropped;
    IF actual_columns IS DISTINCT FROM ARRAY[
        'upload_id:uuid:not_null', 'doc_id:text:not_null', 'source_id:text:not_null',
        'original_filename:text:not_null', 'file_format:text:not_null', 'title:text:not_null',
        'file_size_bytes:integer:not_null', 'chunking_strategy:text:not_null',
        'parser_metadata:jsonb:not_null', 'uploaded_at:timestamp with time zone:not_null',
        'updated_at:timestamp with time zone:not_null', 'row_version:bigint:not_null'
    ]::text[] THEN
        RAISE EXCEPTION 'managed_uploads columns differ from the approved proposal';
    END IF;

    SELECT array_agg(conname::text ORDER BY conname)
      INTO actual_constraints
      FROM pg_catalog.pg_constraint WHERE conrelid = managed_table;
    IF actual_constraints IS DISTINCT FROM ARRAY[
        'managed_uploads_doc_fk', 'managed_uploads_doc_id_key',
        'managed_uploads_file_size_check', 'managed_uploads_filename_check',
        'managed_uploads_format_check', 'managed_uploads_metadata_check',
        'managed_uploads_pkey', 'managed_uploads_row_version_check',
        'managed_uploads_source_doc_fk', 'managed_uploads_source_id_key',
        'managed_uploads_strategy_check', 'managed_uploads_title_check'
    ]::text[] THEN
        RAISE EXCEPTION 'managed_uploads constraints differ from the approved proposal';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_constraint AS c
        WHERE c.conrelid = managed_table AND c.conname = 'managed_uploads_pkey'
          AND c.contype = 'p'
          AND c.conkey = ARRAY[
              (SELECT attnum FROM pg_catalog.pg_attribute
               WHERE attrelid = managed_table AND attname = 'upload_id')
          ]::smallint[]
    ) OR NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_constraint AS c
        WHERE c.conrelid = managed_table AND c.conname = 'managed_uploads_doc_id_key'
          AND c.contype = 'u'
          AND c.conkey = ARRAY[
              (SELECT attnum FROM pg_catalog.pg_attribute
               WHERE attrelid = managed_table AND attname = 'doc_id')
          ]::smallint[]
    ) OR NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_constraint AS c
        WHERE c.conrelid = managed_table AND c.conname = 'managed_uploads_source_id_key'
          AND c.contype = 'u'
          AND c.conkey = ARRAY[
              (SELECT attnum FROM pg_catalog.pg_attribute
               WHERE attrelid = managed_table AND attname = 'source_id')
          ]::smallint[]
    ) OR NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_constraint AS c
        WHERE c.conrelid = managed_table AND c.conname = 'managed_uploads_doc_fk'
          AND c.contype = 'f' AND c.confdeltype = 'r'
          AND c.confrelid = 'public.documents'::regclass
          AND c.conkey = ARRAY[
              (SELECT attnum FROM pg_catalog.pg_attribute
               WHERE attrelid = managed_table AND attname = 'doc_id')
          ]::smallint[]
          AND c.confkey = ARRAY[
              (SELECT attnum FROM pg_catalog.pg_attribute
               WHERE attrelid = c.confrelid AND attname = 'doc_id')
          ]::smallint[]
    ) OR NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_constraint AS c
        WHERE c.conrelid = managed_table AND c.conname = 'managed_uploads_source_doc_fk'
          AND c.contype = 'f' AND c.confdeltype = 'r'
          AND c.confrelid = 'public.document_sources'::regclass
          AND c.conkey = ARRAY[
              (SELECT attnum FROM pg_catalog.pg_attribute
               WHERE attrelid = managed_table AND attname = 'source_id'),
              (SELECT attnum FROM pg_catalog.pg_attribute
               WHERE attrelid = managed_table AND attname = 'doc_id')
          ]::smallint[]
          AND c.confkey = ARRAY[
              (SELECT attnum FROM pg_catalog.pg_attribute
               WHERE attrelid = c.confrelid AND attname = 'source_id'),
              (SELECT attnum FROM pg_catalog.pg_attribute
               WHERE attrelid = c.confrelid AND attname = 'doc_id')
          ]::smallint[]
    ) THEN
        RAISE EXCEPTION 'managed_uploads source/document ownership constraint is missing';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_constraint
        WHERE conrelid = managed_table AND conname = 'managed_uploads_file_size_check'
          AND contype = 'c'
          AND pg_catalog.pg_get_constraintdef(oid) LIKE '%file_size_bytes >= 1%'
          AND pg_catalog.pg_get_constraintdef(oid) LIKE '%file_size_bytes <= 5242880%'
    ) OR NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_constraint
        WHERE conrelid = managed_table AND conname = 'managed_uploads_filename_check'
          AND contype = 'c'
          AND pg_catalog.pg_get_constraintdef(oid) LIKE '%char_length(original_filename) >= 1%'
          AND pg_catalog.pg_get_constraintdef(oid) LIKE '%char_length(original_filename) <= 255%'
    ) OR NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_constraint
        WHERE conrelid = managed_table AND conname = 'managed_uploads_title_check'
          AND contype = 'c'
          AND pg_catalog.pg_get_constraintdef(oid) LIKE '%char_length(title) >= 1%'
          AND pg_catalog.pg_get_constraintdef(oid) LIKE '%char_length(title) <= 300%'
    ) OR NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_constraint
        WHERE conrelid = managed_table AND conname = 'managed_uploads_format_check'
          AND contype = 'c'
          AND pg_catalog.pg_get_constraintdef(oid) LIKE '%pdf%'
          AND pg_catalog.pg_get_constraintdef(oid) LIKE '%docx%'
          AND pg_catalog.pg_get_constraintdef(oid) LIKE '%txt%'
          AND pg_catalog.pg_get_constraintdef(oid) LIKE '%md%'
          AND length(pg_catalog.pg_get_constraintdef(oid))
              - length(replace(pg_catalog.pg_get_constraintdef(oid), chr(39), '')) = 8
    ) OR NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_constraint
        WHERE conrelid = managed_table AND conname = 'managed_uploads_strategy_check'
          AND contype = 'c'
          AND pg_catalog.pg_get_constraintdef(oid) LIKE '%paragraph%'
          AND pg_catalog.pg_get_constraintdef(oid) LIKE '%fixed_overlap%'
          AND length(pg_catalog.pg_get_constraintdef(oid))
              - length(replace(pg_catalog.pg_get_constraintdef(oid), chr(39), '')) = 4
    ) OR NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_constraint
        WHERE conrelid = managed_table AND conname = 'managed_uploads_metadata_check'
          AND contype = 'c'
          AND pg_catalog.pg_get_constraintdef(oid) LIKE '%jsonb_typeof%'
          AND pg_catalog.pg_get_constraintdef(oid) LIKE '%object%'
          AND length(pg_catalog.pg_get_constraintdef(oid))
              - length(replace(pg_catalog.pg_get_constraintdef(oid), chr(39), '')) = 2
    ) OR NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_constraint
        WHERE conrelid = managed_table AND conname = 'managed_uploads_row_version_check'
          AND contype = 'c'
          AND pg_catalog.pg_get_constraintdef(oid) LIKE '%row_version%'
          AND pg_catalog.pg_get_constraintdef(oid) LIKE '%1%'
    ) THEN
        RAISE EXCEPTION 'managed_uploads checks or unique key definitions are incompatible';
    END IF;

    SELECT array_agg(idx.relname::text ORDER BY idx.relname::text)
      INTO actual_indexes
      FROM pg_catalog.pg_index AS i
      JOIN pg_catalog.pg_class AS idx ON idx.oid = i.indexrelid
     WHERE i.indrelid = managed_table;
    IF actual_indexes IS DISTINCT FROM ARRAY[
        'managed_uploads_doc_id_key', 'managed_uploads_pkey',
        'managed_uploads_source_id_key', 'managed_uploads_uploaded_at_idx'
    ]::text[] OR NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_index AS i
        WHERE i.indrelid = managed_table AND i.indisvalid AND NOT i.indisunique
          AND pg_catalog.pg_get_indexdef(i.indexrelid) ILIKE '%(uploaded_at DESC, upload_id)%'
    ) THEN
        RAISE EXCEPTION 'managed_uploads indexes differ from the approved proposal';
    END IF;

    SELECT array_agg(idx.relname::text ORDER BY idx.relname::text)
      INTO actual_source_indexes
      FROM pg_catalog.pg_index AS i
      JOIN pg_catalog.pg_class AS idx ON idx.oid = i.indexrelid
     WHERE i.indrelid = 'public.document_sources'::regclass;
    IF actual_source_indexes IS DISTINCT FROM ARRAY[
        'document_sources_doc_id_idx', 'document_sources_pkey',
        'document_sources_source_doc_idx', 'document_sources_title_normalized_idx'
    ]::text[] THEN
        RAISE EXCEPTION 'document_sources indexes differ from the approved proposal';
    END IF;

    IF (SELECT pg_catalog.pg_get_expr(d.adbin, d.adrelid)
        FROM pg_catalog.pg_attrdef AS d
        JOIN pg_catalog.pg_attribute AS a
          ON a.attrelid = d.adrelid AND a.attnum = d.adnum
        WHERE d.adrelid = managed_table AND a.attname = 'row_version') IS DISTINCT FROM '1'
       OR (SELECT pg_catalog.pg_get_expr(d.adbin, d.adrelid)
           FROM pg_catalog.pg_attrdef AS d
           JOIN pg_catalog.pg_attribute AS a
             ON a.attrelid = d.adrelid AND a.attnum = d.adnum
           WHERE d.adrelid = managed_table AND a.attname = 'parser_metadata') IS DISTINCT FROM '''{}''::jsonb'
       OR (SELECT pg_catalog.pg_get_expr(d.adbin, d.adrelid)
           FROM pg_catalog.pg_attrdef AS d
           JOIN pg_catalog.pg_attribute AS a
             ON a.attrelid = d.adrelid AND a.attnum = d.adnum
           WHERE d.adrelid = managed_table AND a.attname = 'uploaded_at') IS DISTINCT FROM 'now()'
       OR (SELECT pg_catalog.pg_get_expr(d.adbin, d.adrelid)
           FROM pg_catalog.pg_attrdef AS d
           JOIN pg_catalog.pg_attribute AS a
             ON a.attrelid = d.adrelid AND a.attnum = d.adnum
           WHERE d.adrelid = managed_table AND a.attname = 'updated_at') IS DISTINCT FROM 'now()'
       OR EXISTS (
           SELECT 1 FROM pg_catalog.pg_trigger
           WHERE tgrelid = managed_table AND NOT tgisinternal
       ) THEN
        RAISE EXCEPTION 'managed_uploads defaults or trigger set differs from the approved proposal';
    END IF;

    IF source_pair_index IS NULL OR NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_index AS i
        WHERE i.indexrelid = source_pair_index
          AND i.indrelid = 'public.document_sources'::regclass
          AND i.indisunique AND i.indisvalid
          AND pg_catalog.pg_get_indexdef(i.indexrelid) LIKE '%(source_id, doc_id)%'
    ) THEN
        RAISE EXCEPTION 'the approved document_sources pair index is missing or incompatible';
    END IF;

    IF EXISTS (SELECT 1 FROM pg_catalog.pg_policy WHERE polrelid = managed_table)
       OR has_table_privilege('anon', managed_table, 'SELECT')
       OR has_table_privilege('anon', managed_table, 'INSERT')
       OR has_table_privilege('anon', managed_table, 'UPDATE')
       OR has_table_privilege('anon', managed_table, 'DELETE')
       OR has_table_privilege('authenticated', managed_table, 'SELECT')
       OR has_table_privilege('authenticated', managed_table, 'INSERT')
       OR has_table_privilege('authenticated', managed_table, 'UPDATE')
       OR has_table_privilege('authenticated', managed_table, 'DELETE')
       OR NOT has_table_privilege('service_role', managed_table, 'SELECT')
       OR NOT has_table_privilege('service_role', managed_table, 'INSERT')
       OR NOT has_table_privilege('service_role', managed_table, 'UPDATE')
       OR NOT has_table_privilege('service_role', managed_table, 'DELETE')
       OR EXISTS (
           SELECT 1 FROM pg_catalog.pg_class AS c
           CROSS JOIN LATERAL aclexplode(
               COALESCE(c.relacl, acldefault('r', c.relowner))
           ) AS acl
           WHERE c.oid = managed_table AND acl.grantee = 0
       ) THEN
        RAISE EXCEPTION 'managed_uploads RLS policies or grants are not backend-only';
    END IF;
END
$$;
