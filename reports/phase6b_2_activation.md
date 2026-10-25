# Phase 6B.2 — Database Verification and Controlled Activation

## Status: BLOCKED before production SQL

The user authorized the additive migration only after a fresh Frankfurt
preflight. This session has no connected Supabase database operation tool. The
available database-related connector is for Cloudflare D1, not Supabase. I did
not substitute the local `DATABASE_URL`, access Frankfurt directly, or rely on
the previous owner-reported counts as a fresh verification. No production SQL,
CRUD operation, or deployment was attempted. Mindo and Sydney were not
contacted; the held-out evaluation set was not accessed.

At the start, `HEAD` and `origin/master` were both
`77eb2d4729903991944f197be2d384084de008a1`. The user's read-only figures
(PostgreSQL 17.11, 50,000 documents, 50,018 sources, and 50,000 chunks) are
recorded as **owner-reported, not independently verified in this turn**.
No migration statement was executed, so there is no actual after-count
measurement; the source counts must be re-read through the connected tool
before claiming that they remain unchanged.

## Preflight findings

I read the complete
`migrations/proposals/phase6b_managed_uploads.sql` and checked the local
migration directory. It contains the existing base `migrations/schema.sql` and
this one Phase 6B proposal; there is no second local Phase 6B migration file.
Static review finds the proposal limited to:

- the approved unique `document_sources_source_doc_idx` on
  `(source_id, doc_id)`;
- `public.managed_uploads`, its constraints and listing index;
- RLS enablement, revoking `PUBLIC`/`anon`/`authenticated`, granting table CRUD
  to `service_role`, and the final catalog validation block.

I found no `DROP`, `TRUNCATE`, `DELETE`, or corpus-row `UPDATE` statement. The
composite foreign key pairs the managed row's `source_id` with its `doc_id`.
The SQL places index creation before table creation, so it must be run in the
single transaction requested, allowing both DDL and grants to roll back on any
error. No obvious destructive statement or out-of-scope table change was found
in the source review. This is not a PostgreSQL syntax check: without a database
connection I cannot confirm PostgreSQL 17.11 parses and executes the full block
or that its catalog checks match the live schema.

| Required check | Result |
|---|---|
| Connected project is exactly `nldnpqhqrfwjgxcqeuru` | **Not checked — connector unavailable** |
| Existing counts and schema objects match | **Not checked — owner-reported figures only** |
| No conflicting live migration or unexpected schema object | **Not checked live** |
| Backup, restore procedure, and available storage | **Not checked** |
| `managed_uploads` absent/empty | **Not checked live** |
| Migration applied atomically | **No — not applied** |
| After-counts, RLS, grants, foreign keys, and search objects | **Not checked live** |

The activation gate therefore remains **BLOCKED**. No after-count is inferred.

## How to unblock

Enable a Supabase database connector for this workspace that can read the
project identity/schema/counts and apply one explicit SQL migration to the
Frankfurt project. Then rerun the fresh preflight, compare against the exact
expected counts, verify backup/restore and storage headroom, and abort on any
unexpected object or result. The prior user approval remains conditional on
those gates. Do not use a Cloudflare D1 connector or an unverified local DSN as
a substitute.

The owner accepted that isolated PostgreSQL testing was unavailable; I did not
start another Docker setup milestone. If the Supabase connector becomes
available, the production migration itself still must run in one transaction
with reasonable lock and statement timeouts. Any SQL error must roll back the
transaction, be reported verbatim after secret scrubbing, and stop the run;
do not retry blindly.

## Render handoff (not deployed)

The application commit containing Phase 6B is
`bf1e9c636a6fda2db53496e6e9e27e64a584bdb2`. The current later commit
`77eb2d4729903991944f197be2d384084de008a1` is documentation-only. Render access
is unavailable, so no live environment variable or `ADMIN_TOKEN` check was
possible. The token value was not read or printed in this turn.

From `render.frankfurt.yaml`:

```text
Build: pip install -r requirements.txt && python scripts/download_model.py
Start: uvicorn app.main:app --host 0.0.0.0 --port $PORT --no-proxy-headers
Health: /health
Service: evidence-ai-frankfurt, Frankfurt region, free plan
```

Variable names declared by that Blueprint are `PYTHON_VERSION`,
`ENABLE_EMBEDDING_STARTUP_CHECK`, `FASTEMBED_MODEL`, `GEMINI_MODEL`,
`INVESTIGATION_DAILY_BUDGET`, `INVESTIGATION_PER_IP_PER_MINUTE`,
`INVESTIGATION_MAX_CONCURRENT`, `INVESTIGATION_TIMEOUT_SECONDS`,
`GEMINI_REQUEST_TIMEOUT_SECONDS`, `GEMINI_MAX_OUTPUT_TOKENS`,
`DATABASE_STATEMENT_TIMEOUT_MS`, `INDEXED_DOCUMENT_COUNT`, `DATABASE_URL`,
`GEMINI_API_KEY`, and `ADMIN_TOKEN`. Render provides `PORT`.

**Do not sync the Blueprint unchanged:** it declares
`INVESTIGATION_DAILY_BUDGET=0`, which disables investigations and could replace
the operator's positive production setting. Preserve the positive budget,
`GEMINI_API_KEY`, and `DATABASE_URL`. `ADMIN_TOKEN` is configured manually in
Render; check that it is at least 32 characters without logging or exposing it.
The app code enforces this minimum for admin operations, but live Render
configuration was not accessible here.

## Minimal post-deployment TXT smoke test

Run only after the database gates and migration succeed and the operator
manually deploys the Frankfurt service:

1. Open `https://<Frankfurt-service-host>/library`.
2. Enter the administrator token in the page's auth control; never put it in a
   URL or browser local storage.
3. Upload one small TXT file with a unique fact and record its upload ID and
   content-addressed document ID.
4. Search/investigate a question whose answer is in that file; verify its title,
   chunk citation, and exact quote.
5. Replace the file with different unique text. Confirm the document ID changes
   and the new fact can be retrieved.
6. Delete only the recorded synthetic upload ID. Confirm the upload disappears
   and its test content is no longer retrieved.
7. Compare final documents/sources/chunks counts with the verified baseline
   (50,000 / 50,018 / 50,000); confirm no managed test row remains and the
   original corpus records remain intact.
8. In Render Metrics, inspect memory during the upload and compare peak usage
   with 512 MiB (`536870912` bytes). Startup logs provide
   `application_startup_memory`; request logs currently provide
   `investigation_memory` RSS, but there is no per-upload RSS event. Use the
   Render memory graph for the upload interval.

Stop on any unexpected result. Do not use a corpus record for update/delete or
run broad cleanup.

## Verification performed

The full local suite was rerun:

```powershell
.\.venv\Scripts\python -m pytest -q
```

Result: **192 passed**. These are local tests and do not verify live PostgreSQL,
Render secrets, production counts, migration execution, or live CRUD. The final
production migration status remains **not applied**; all live checks above are
unverified. Do not begin Phase 7.
