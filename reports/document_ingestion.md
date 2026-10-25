# Document ingestion and management

This report covers the original Phase 6B implementation and chunking
comparison. **The deployment status in this report is historical:** during
the initial tests, the managed-upload migration had not been applied. The
later [activation record](archive/phase6b_2_activation.md) reports that it
was applied to Frankfurt. Subsequent live upload, replacement, and deletion
checks are summarized in the
[requirements coverage](final_submission_checklist.md). Those later checks
are recorded as owner-reported, not independently repeated here.

## Initial implementation and safety checks

At the Phase 6B checkpoint, the parser, transactional ownership layer,
authenticated API, and library page were implemented and tested locally.
No production migration, Supabase write, or Render deployment took place
*during that initial milestone*. The existing 50K corpus and evaluation
datasets were not changed by the chunking comparison.

The document API depends on the
[managed-upload migration](../migrations/proposals/phase6b_managed_uploads.sql)
and returns a sanitized temporary-unavailable response if that table
is missing.

## Implementation

- `POST /api/documents` parses, chunks, embeds, and indexes an upload.
- `GET /api/documents` lists only rows in the ownership table; `GET
  /api/documents/{upload_id}` returns its text and metadata.
- `PUT /api/documents/{upload_id}` replaces a managed upload.
- `DELETE /api/documents/{upload_id}` removes that upload's ownership and source
  provenance, deleting canonical document/chunks only when no source still
  references them.
- Every document endpoint, including list/inspect, requires a configured Bearer
  `ADMIN_TOKEN` of at least 32 characters. The library keeps it in page memory,
  clears the password field after entry, and does not use browser storage or URLs.
- Upload request bodies allow at most 5 MiB plus multipart framing. Extracted
  text is capped at 200,000 characters; PDFs at 200 pages; DOCX archives at
  2,000 entries and 20 MiB expanded size.
- Parser support: text-based PDF via `pypdf`, DOCX via `python-docx`, UTF-8 TXT,
  and Markdown treated as text (with an H1 title when available). A PDF with no
  extractable text is rejected as scanned/image-only; OCR is not provided.
- Parser metadata includes available PDF/DOCX author, title, creator/subject,
  dates, page count, or text encoding. Filename, format, title, byte size,
  upload/update timestamps, parser metadata, title alias, and upload provenance
  are held in the proposed owner table/source row.
- Upload text is stored once as `documents.full_text`; chunk rows retain stable
  IDs and character offsets. Search reconstructs excerpts using the existing
  schema and existing semantic, FTS keyword, and hybrid paths. Semantic remains
  the investigation default.
- The service passes the single FastEmbed model loaded at startup into the
  upload handler. It embeds before opening the final write transaction, so no
  database transaction stays open during embedding. Embeddings are validated as
  finite 384-dimensional vectors.
- Write updates are guarded by a monotonic `row_version` read under `FOR UPDATE`;
  timestamps are no longer used as the concurrency token. The ASGI body limiter
  permits one upload/update at a time per process and returns 429 for overlapping
  writes, bounding simultaneous multipart and embedding work within one worker.

### Identity, deduplication, and ownership

Document identity uses the project's existing normalized content hash. Create
rejects content already present in the corpus or upload index before adding any
source or ownership row. A concurrent insert collision also rolls back. An
upload never adopts an existing corpus document. Replacement of changed content
inserts a new content ID and switches the ownership row in one transaction; it
does not update `full_text` under the old hash. Delete removes only the upload's
own source and manager row. A document with any other provenance remains
searchable and is not deleted. Strategy replacement is refused when the
document has other source aliases because chunks are shared by content ID.

The proposal creates `public.managed_uploads`, a timestamp listing index, and a
unique `(source_id, doc_id)` index on `document_sources`, plus constraints, RLS,
and service-role grants. The composite foreign key prevents an owner row from
pointing at a source belonging to a different document. It does not drop,
truncate, rewrite, or delete existing tables or records. No migration is run
during startup.

## Chunking comparison

Command:

```powershell
.\.venv\Scripts\python -m scripts.compare_chunking
```

The comparison is deterministic and uses one synthetic 1,548-character fixture,
three answer-supporting sentences, three natural-language questions, and BGE
`BAAI/bge-small-en-v1.5` loaded from the existing local model cache in offline
mode. The candidate set contains only fixture chunks; it does not use the corpus
or either evaluation set.

| Strategy | Chunks | Stored chunk characters | Support sentence coverage | Fixture semantic Recall@1 | Fixture MRR |
|---|---:|---:|---:|---:|---:|
| Paragraph | 4 | 1,542 | 3/3 (100%) | 1.00 | 1.00 |
| Fixed 1,000 chars, 150 overlap | 2 | 1,698 | 3/3 (100%) | 1.00 | 1.00 |

The paragraph chunks were 402, 384, 387, and 369 characters; six blank-line
separator characters are omitted from chunk text. Fixed chunks were 1,000 and
698 characters, with 150 repeated overlap characters. Query embeddings were
shared across strategies. In this local run, shared query embedding took 25.5
ms; passage embeddings took 136.5 ms for paragraph chunks and 179.9 ms for
fixed-overlap chunks. These are single local timings on tiny batches, not
capacity or latency estimates.

Both strategies ranked all three synthetic evidence passages first. This tiny,
constructed candidate set does not establish retrieval quality on the 50K
corpus. No production database retrieval benchmark or corpus reindex was run.
The original paragraph strategy respects source paragraph boundaries and avoids
overlap duplication. Managed uploads additionally split paragraphs longer than
1,000 characters; the Phase 1E corpus chunking defaults are unchanged. The fixed
strategy uses overlapping 1,000-character windows. A maximum upload of 200,000
characters produces at most 200 paragraph chunks for one long paragraph or 236
fixed-overlap chunks. More than 250 chunks (for example, a file made of many
tiny paragraphs) is rejected before embedding. Fixed windows preserve adjacent
context at the cost of overlap storage and possible cuts inside sentences/words.

## Security, resource bounds, and limitations

- Credentials remain server-side. API errors and logs omit exception messages,
  DSNs, and token values; logs include only operation name and exception type.
- The HTML uses `textContent` for returned filenames, titles, and document text.
- The ownership table has RLS enabled, revokes `PUBLIC`, `anon`, and
  `authenticated` table access, and grants CRUD only to `service_role`; no
  browser Supabase key is used. Backend DB access still depends on the private
  server-side `DATABASE_URL` and existing project-identity guard.
- The 5 MiB request cap, one concurrent write per process, 200,000-character
  extraction cap, 250-chunk cap, 200-page PDF limit, and 20 MiB DOCX expansion
  cap bound parser/embedding work. The middleware still buffers one bounded
  request body while FastAPI parses it, so peak RAM may exceed the file size.
  No Render upload RSS measurement is claimed because this change was not
  deployed. Verify uploads under the live 512 MiB plan after schema approval.
- A local Windows HTTP smoke check returned 200 for `/`, `/library`, and
  `/health`; the root displayed the 50,000-record count and linked the library.
  Startup RSS was 228,982,784 bytes and peak RSS was 262,832,128 bytes after
  loading the cached model. These are local startup readings only, not Render
  or upload-memory evidence. The local document API returned 503 because the
  environment did not provide a 32-character admin token; it failed closed
  before database access.
- PDF reading order and DOCX header/footer/footnote extraction are not
  normalized; no OCR, remote URL import, raw-file retention, or public admin
  session is implemented. The owner must upload a replacement file again to
  update content; uploaded source sentences are empty because no trusted source
  sentence annotations are supplied, while citations use reconstructed chunks.
- The new API has no PostgreSQL integration result: mocked transaction tests
  check application write ordering/rollback/ownership rules, not the PostgreSQL
  parser, grants, or live trigger execution.

## Tests and reproduction

Run the complete suite and the strategy comparison from the repository root:

```powershell
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python -m scripts.compare_chunking
```

The Phase 6B baseline passed **181 tests**. Phase 6B.1 results are recorded in
[Phase 6B.1 safety review](archive/phase6b_1_safety_review.md). Existing tests cover UTF-8 parsing,
text PDF/DOCX extraction, scanned-PDF rejection, malformed/empty/oversized
files, chunk offsets, both chunkers,
authentication, safe API errors, content deduplication, rollback, replacement,
delete ownership, and retrieval of managed-upload provenance. The tests use
fixtures/fakes and do not connect to Supabase.

## Original deployment checklist

These steps belonged to the initial implementation. Later reports describe
progress on migration and live testing; **do not reapply the migration** just
because it appears in this earlier checklist.

1. Review the ownership-table migration and check the database's current
   state before applying any schema change.
2. Keep a random 32+ character `ADMIN_TOKEN` in local/Render secrets, never
   in source control or browser storage.
3. Verify upload, replacement, deletion, and resource use on the deployed
   app. Repeated/concurrent memory checks remain a separate limitation.

If the owner later rolls back the application code, leave the table and uploaded
data in place. Dropping `managed_uploads` would remove ownership records and make
uploads difficult to manage; any such destructive operation requires a separate
review, export, and explicit approval. No destructive SQL was proposed or
executed here.
