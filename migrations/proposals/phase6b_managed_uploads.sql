-- PROPOSAL ONLY — do not run without explicit owner approval.
-- Additive metadata for admin-managed uploads; no existing corpus rows are changed.
-- The backend inserts this row only after it inserted a previously absent doc_id.
CREATE TABLE public.managed_uploads (
    upload_id uuid PRIMARY KEY,
    doc_id text NOT NULL UNIQUE
        REFERENCES public.documents(doc_id) ON DELETE RESTRICT,
    source_id text NOT NULL UNIQUE
        REFERENCES public.document_sources(source_id) ON DELETE RESTRICT,
    original_filename text NOT NULL
        CHECK (char_length(original_filename) BETWEEN 1 AND 255),
    file_format text NOT NULL
        CHECK (file_format IN ('pdf', 'docx', 'txt', 'md')),
    title text NOT NULL CHECK (char_length(title) BETWEEN 1 AND 300),
    file_size_bytes integer NOT NULL
        CHECK (file_size_bytes BETWEEN 1 AND 5242880),
    chunking_strategy text NOT NULL
        CHECK (chunking_strategy IN ('paragraph', 'fixed_overlap')),
    parser_metadata jsonb NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(parser_metadata) = 'object'),
    uploaded_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX managed_uploads_uploaded_at_idx
    ON public.managed_uploads (uploaded_at DESC, upload_id);

ALTER TABLE public.managed_uploads ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.managed_uploads FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.managed_uploads TO service_role;
GRANT USAGE ON SCHEMA public TO service_role;
