# Phase 6B.1 — Pre-Deployment Safety and Database Compatibility

## Status and safety boundary

The review and local code changes are complete. The Phase 6B proposal migration
was **not applied**. This work did not connect to Supabase, read or write any
production table, change Render, deploy, use either evaluation candidate file,
or modify the 50,000-document corpus. The `.env` file was not inspected. Mindo
and Sydney were not contacted. The owner’s existing unstaged `AGENTS.md` edit
was left out of the changes.

PostgreSQL integration is **pending**: no `psql` or Docker executable and no
local PostgreSQL Windows service were available. Fixture tests are not a
substitute for running this proposal and CRUD code against PostgreSQL.

## Findings and changes

### Legacy schema guards

Phase 5 and Phase 1C ingestion previously rejected any public table beyond
`documents`, `document_sources`, and `chunks`. The approved proposal adds only
`managed_uploads` and the explicitly named
`document_sources_source_doc_idx` unique index. The application schema helper
and Phase 5 validator now allow that one table only after validating its exact
columns, constraints, indexes, RLS, grants, default values, and absence of
policies/triggers. They still reject every other public relation and preserve
the original Frankfurt project identity guard and corpus checks.

Both legacy writers stop before database writes when `managed_uploads` contains
any rows. Their commands must not be run after the first managed upload:

```powershell
python scripts/ingest_hotpotqa.py
python scripts/ingest_phase5.py --limit 50000 --threads 4
```

Do not use a different limit to bypass the operational stop. The read-only
`scripts/measure_db_size.py` remains available. Capacity projections now count
the approved managed table as fixed relation storage rather than scaling it
with corpus document count.

### Migration and ownership

The proposal remains additive and contains no `DROP`, `TRUNCATE`, `DELETE`, or
corpus-row `UPDATE`. It creates the managed table and listing index, plus a
unique index on `(source_id, doc_id)`. The migration is repeatable with
`IF NOT EXISTS`, then checks the exact column, constraint, index, RLS, grant,
default, and trigger definitions so an incompatible same-named object fails
closed. Reapplying the approved schema preserves any managed rows.

The previous two independent foreign keys allowed a manager row to pair a
document with a source owned by another document. The revised proposal retains
the document foreign key and adds a composite source/document foreign key with
`ON DELETE RESTRICT`. PostgreSQL requires referenced columns to be unique, so
the additive pair index supports that constraint. The managed row’s unique
document and source keys also keep one upload owner from claiming shared or
pre-existing content.

RLS stays enabled. The proposal grants CRUD only to the server-side
`service_role`, revokes `PUBLIC`, `anon`, and `authenticated`, and defines no
policies. The schema validator checks those grants independently from RLS.
The HTTP admin token remains a separate server-side gate; no credential was
added to browser storage or a URL.

Rollback is application rollback only: leave the additive table, indexes, and
any managed data in place if reverting the web code. Dropping the ownership
table or either index is not an automatic rollback and would require a separate
backup, dependency review, and explicit approval.

### CRUD and retrieval review

- Upload creates a content-addressed document only when the insert succeeds.
  An existing content ID returns a duplicate conflict before a manager row is
  created; an insert race is handled by the same `ON CONFLICT DO NOTHING`
  check inside the transaction. Corpus documents therefore cannot acquire an
  upload owner through duplicate content.
- Replace inserts changed text under its new stable ID, then switches ownership
  and removes only the upload’s old provenance in one transaction. It never
  changes canonical text under an old hash. Same-content title/filename changes
  keep the canonical document. Transaction exceptions roll back the whole
  change.
- Delete requires an upload ID, locks the managed row, deletes that row and its
  own source, then deletes the canonical document only if no source or managed
  row still references it. Database `RESTRICT` foreign keys add a second guard.
- The old concurrency token was `updated_at`; PostgreSQL transaction timestamps
  can be identical for concurrent edits. The migration now has a checked
  monotonic `row_version`. Replace compares it after `SELECT ... FOR UPDATE` and
  increments it in the same transaction. A stale second update fails. Delete
  and replace serialize on the owner row; a replace after a completed delete
  returns not found.
- Read queries now join the stored provenance source on both `source_id` and
  `doc_id`, in addition to the database constraint.
- Chunk reconstruction still uses the existing canonical `full_text` and
  character offsets. Uploaded title aliases flow through the existing FTS
  trigger; retrieval returns the existing stable chunk IDs and sources, so
  semantic, keyword, hybrid, and exact-quote citation paths remain compatible.

### Resource and authentication review

Parser limits remain 5 MiB per file, 200,000 extracted characters, 200 PDF
pages, 2,000 DOCX archive entries, and 20 MiB expanded DOCX content. Paragraph
chunking for uploaded documents now splits a single paragraph at 1,000
characters; historical corpus chunking is unchanged. With a 200,000-character
input, one paragraph produces 200 paragraph chunks and fixed-overlap chunking
produces 236 chunks (1,000 size, 150 overlap). Files requiring more than 250
chunks are rejected before embeddings. This bounds one upload to at most ten
25-chunk embedding batches.

The request-body middleware coalesces body fragments into one bounded buffer
before FastAPI parses it, avoiding memory amplification from many tiny ASGI
fragments. It admits only one upload/update at a time **per process** and
returns HTTP 429 with `Retry-After: 1` for another overlapping write. This limits
concurrent buffered files and embedding batches on the configured
single-worker service; it is not a cross-process or cross-instance quota. A
malformed file can still consume parser/CPU time within the byte, page, archive,
character, and chunk bounds. The administrator token is required before API
operations and remains in the page’s memory only.

No new dependency was added. The prior Phase 6B local startup RSS values
(228,982,784 bytes current and 262,832,128 bytes peak) do not measure upload
parsing, embeddings, or concurrent production requests. There is **no Render
upload memory result** and no claim that uploads fit under Render Free’s 512
MiB limit. Deployment must separately measure idle/startup RSS, repeated real
uploads/investigations, and a two-request overlap from Render logs.

A local synthetic run using the cached BGE model to embed the full 200/236-chunk
upper-bound fixtures continued consuming workstation CPU without returning
measurements and was stopped. No new embedding latency or RSS figure is claimed
from that run.

## Verification

Focused local regression tests cover the exact public-relation allowlist,
managed-table schema/security checks, rejection before legacy schema writes
when manager rows exist, stale replacement versions, replacement after delete,
Unicode offsets with long paragraph splits, the 250-chunk bound, capacity
projection with the additive table, and upload-write concurrency responses.
These use scripted/fake database resources. They do not prove PostgreSQL DDL,
foreign-key execution, grants, triggers, or transaction locking.

The complete local test command passed **192 tests**:

```powershell
.\.venv\Scripts\python -m pytest -q
```

No production SQL or `DATABASE_URL` connection was made. No held-out evaluation
questions were opened.

## Remaining production risks

1. Run the proposal against an explicitly disposable PostgreSQL/Supabase test
   project first. Validate the `DO` block syntax, `pg_get_constraintdef`
   assumptions, grants, composite FK, CRUD transactions, and concurrency with
   the actual database version. This step is pending.
2. The additive unique index build scans the existing provenance table and can
   take a lock and temporary disk space. Schedule it when corpus writes are
   stopped; do not add `CONCURRENTLY` without changing the migration execution
   procedure and testing the result.
3. No real Render memory result exists for maximum-size files, a 250-chunk
   upload, or upload/investigation overlap. Do not mark memory safety verified
   based on startup-only measurements.
4. The per-process upload gate assumes the current one-worker configuration.
   Multiple workers or instances each have an independent gate; the admin API
   has no durable upload-rate quota.
5. Existing runbooks must permanently stop both corpus ingestion writers after
   managed uploads start. The runtime checks fail closed when they observe a
   non-empty owner table, but an operator must avoid starting a writer alongside
   the very first upload.

## Operator checklist for a later activation

This checklist is not approval to execute anything now.

1. **Disposable SQL verification:** Create an explicitly disposable local
   Supabase/PostgreSQL test target with pgvector and the Supabase roles used by
   the existing schema. Apply `migrations/schema.sql`, then the proposal, and
   test create/duplicate/replace/delete/rollback plus mismatched source/document
   rejection and concurrent stale writes. Keep the production identity guard
   unchanged; do not point tests at Frankfurt, Sydney, or Mindo.
2. **Backup and identity:** Before any separately approved production migration,
   verify the connection host identifies Frankfurt project
   `nldnpqhqrfwjgxcqeuru`; inspect the three expected core table counts and take
   a recoverable backup. Confirm `managed_uploads` is absent or already matches
   this exact empty proposal. Abort on any unexpected public relation, count,
   index, or owner row.
3. **Apply only after approval:** Review the complete proposal. Apply it in a
   transaction during a quiet period because the pair index is built on the
   existing provenance table. On any SQL exception, roll back and inspect; do
   not continue from a partially applied result.
4. **Read-only post-check:** Use the application’s fail-closed connection and
   validator before deploying or writing:

   ```powershell
   @'
   from app.db.connection import connect_database
   from app.db.queries import verify_managed_uploads_schema

   with connect_database(autocommit=True) as conn:
       print({"verified": verify_managed_uploads_schema(conn, require_empty=True)})
   '@ | .\.venv\Scripts\python -
   ```

   Also compare document/source/chunk counts with the backup, confirm zero
   managed rows, confirm RLS is enabled and no `anon`/`authenticated`/`PUBLIC`
   grants or policies exist, and verify both named indexes. The check must not
   print a connection string or credentials.
5. **Operational handoff:** Set a strong 32+ character `ADMIN_TOKEN` as a
   server-side secret; deploy only after separate approval. Stop all
   `scripts/ingest_hotpotqa.py` and `scripts/ingest_phase5.py` runs before the
   first managed upload. Use an isolated disposable database for CRUD smoke
   tests. Any requested production CRUD or Render deployment requires its own
   explicit approval and post-deployment memory review.

RLS and grants are both checked because table privileges determine whether a
role can access a table at all, while RLS determines which rows it can access.
The composite source/document key uses PostgreSQL’s supported reference to a
unique index. See the [Supabase RLS guide](https://supabase.com/docs/guides/database/postgres/row-level-security)
and [PostgreSQL constraint documentation](https://www.postgresql.org/docs/current/ddl-constraints.html).
