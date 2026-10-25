# Phase 6B.2 — Database Verification and Controlled Activation

**Status: blocked before production preflight and writes.** The disposable
PostgreSQL gate could not be run because this workstation has no PostgreSQL
client/server, Docker command, PostgreSQL service, or local listener on port
5432. Per the activation rules, the Frankfurt project was not used as a test
database. The migration was not applied, no production connection was opened,
and no Render setting or deployment was changed.

The starting application commit was
`bf1e9c636a6fda2db53496e6e9e27e64a584bdb2`; at inspection, `origin/master`
pointed to the same commit. No held-out evaluation data was accessed. Mindo
and Sydney were not contacted. The existing unstaged `AGENTS.md` edit remains
untouched.

## Gate results

| Gate | Result | Evidence / limitation |
|---|---|---|
| Disposable PostgreSQL available | **Blocked** | `psql`, `pg_ctl`, `initdb`, and `docker` are unavailable; no PostgreSQL service was listed; `127.0.0.1:5432` refused the probe. |
| Migration syntax and constraints | **Not tested** | No real PostgreSQL target; migration was not run. |
| Composite source/document FK | **Not tested** | Requires real catalog and constraint verification. |
| RLS and grants | **Not tested** | No database connection was made. |
| Upload/duplicate/replace/delete/rollback/concurrency | **Not tested against PostgreSQL** | Prior 192-test suite uses local/unit fixtures; it is not PostgreSQL integration evidence. |
| Retrieval after upload | **Not tested against PostgreSQL** | Requires successful disposable CRUD setup. |
| Frankfurt identity and baseline counts | **Not checked live** | Static code still pins the expected project ref to `nldnpqhqrfwjgxcqeuru`; no connection was attempted. The requested 50,000 / 50,018 / 50,000 counts remain unverified in this milestone. |
| Storage headroom and recoverable backup | **Not verified** | No live DB inspection or backup/restore test. Corpus reproducibility is not counted as a backup. |
| Legacy ingestion processes stopped | **Not verified** | No production host/process access. |
| Migration status | **Not applied** | No SQL was executed. |
| PDF, DOCX, TXT, Markdown live CRUD | **Not run** | No synthetic production documents were created. |

The local settings check printed only booleans: local `ADMIN_TOKEN` is absent
and therefore does not meet the 32-character minimum. This says nothing about
Render's secret: Render access is unavailable, and the secret value was never
printed or exposed. The application requires at least 32 characters before
admin document operations; the Render secret must be checked by its owner
before deployment.

## Shortest practical path to unblock PostgreSQL verification

Install and start Docker Desktop (or a compatible Podman runtime). In a new
temporary directory (not linked to any hosted project), initialize and start a
local Supabase stack. The Supabase CLI (2.75.0) and Node.js (24.11.1) are
already installed here; Docker and Podman are the missing pieces:

```powershell
New-Item -ItemType Directory -Force "$env:TEMP\EvidenceAI-Phase6B2-Test" | Out-Null
Set-Location "$env:TEMP\EvidenceAI-Phase6B2-Test"
supabase init
supabase start
supabase status
```

Do **not** run `supabase link`, use a Frankfurt/Sydney/Mindo URL, or copy a
production credential into this environment. Supabase documents that the local
stack runs in containers and requires a container runtime; `init` creates local
configuration and `start` launches the local stack. Do not share the `status`
output because it includes local credentials. See the [official local
development guide](https://supabase.com/docs/guides/local-development/cli/getting-started).

After the local stack is available, resume with a test-only integration runner
that accepts a separate `PHASE6B_TEST_DATABASE_URL` and refuses non-local
hosts. It must create the `extensions` schema and Supabase roles required by
the project, apply `migrations/schema.sql` and then the proposal, and exercise
the actual CRUD/retrieval functions. Keep the production `DATABASE_URL` and its
Frankfurt-only guard unchanged. This runner has not been created or executed;
therefore the database integration gate remains blocked.

## Production migration and CRUD status

No production preflight was attempted because the required isolated
PostgreSQL validation failed. Accordingly, this report has no actual before or
after counts, size/headroom measurements, grant checks, backup verification,
or CRUD results for any format. No document IDs or upload IDs were created.

If the disposable integration gate passes, the user's conditional activation
authorization still requires every production gate below to pass before any
write:

1. Confirm Frankfurt project identity, exact relation/index allowlist, the
   requested baseline counts, storage headroom, and stopped corpus writers.
2. Create and verify a recoverable backup plus a documented restore procedure.
   Do not treat `data/corpus.jsonl` as the backup.
3. During a quiet period, run only
   `migrations/proposals/phase6b_managed_uploads.sql` in one transaction with
   bounded lock and statement timeouts selected from the disposable run. On
   any error, roll back and stop.
4. Check the managed table, composite index/FK, RLS, grants, and unchanged
   original row counts before any synthetic upload.
5. Create a ledger of synthetic upload IDs and unique content. For each of
   PDF, DOCX, TXT, and Markdown, verify upload, retrieval, exact quote, changed
   content's new ID, replacement, and deletion. Verify no test records remain
   and compare final corpus counts to the verified baseline. Stop on an
   unexpected error; do not run broad cleanup.

If the transactional migration succeeds but the application must be rolled
back, roll back the application deployment while leaving the additive table,
index, and any records in place. Do not drop schema objects or delete records
as an automatic rollback. If SQL fails within the migration transaction,
roll back that transaction and inspect the database before retrying. A
production restore path is **not yet verified** and must be established before
activation.

## Render deployment handoff

Render was not accessed and deployment was not performed. The application
commit prepared for deployment is
`bf1e9c636a6fda2db53496e6e9e27e64a584bdb2`.

The separate Frankfurt Blueprint currently specifies:

```text
Build: pip install -r requirements.txt && python scripts/download_model.py
Start: uvicorn app.main:app --host 0.0.0.0 --port $PORT --no-proxy-headers
Health check: /health
Service: evidence-ai-frankfurt (Frankfurt region, free plan)
```

Required/configured variable names in `render.frankfurt.yaml` are:
`PYTHON_VERSION`, `ENABLE_EMBEDDING_STARTUP_CHECK`, `FASTEMBED_MODEL`,
`GEMINI_MODEL`, `INVESTIGATION_DAILY_BUDGET`,
`INVESTIGATION_PER_IP_PER_MINUTE`, `INVESTIGATION_MAX_CONCURRENT`,
`INVESTIGATION_TIMEOUT_SECONDS`, `GEMINI_REQUEST_TIMEOUT_SECONDS`,
`GEMINI_MAX_OUTPUT_TOKENS`, `DATABASE_STATEMENT_TIMEOUT_MS`,
`INDEXED_DOCUMENT_COUNT`, `DATABASE_URL`, `GEMINI_API_KEY`, and `ADMIN_TOKEN`.
Render supplies `PORT`.

**Configuration hazard:** the checked-in Frankfurt Blueprint sets
`INVESTIGATION_DAILY_BUDGET` to `0`, which disables investigations. The owner
reported a positive live budget. Do not sync/deploy this Blueprint while that
setting would overwrite the positive value. Preserve the existing
`DATABASE_URL`, `GEMINI_API_KEY`, and positive daily budget; do not print their
values. `ADMIN_TOKEN` is declared as a manual secret (`sync: false`), but its
live length cannot be verified from this workspace.

After all gates pass and the owner is ready to deploy:

1. In Render, use the separate `evidence-ai-frankfurt` service/Blueprint and
   confirm its region is Frankfurt; preserve the existing Sydney service.
2. Select commit
   `bf1e9c636a6fda2db53496e6e9e27e64a584bdb2` for the manual deployment.
3. Confirm the build/start/health commands above. Keep
   `ENABLE_EMBEDDING_STARTUP_CHECK=true` and the existing BGE model setting.
4. Preserve the current positive daily budget and the approved secret values;
   do not accept the Blueprint's zero budget as a replacement. Check that the
   admin token is at least 32 characters without logging it.
5. Review build logs for the offline model check, then verify startup logs and
   `GET /health` before opening `/library`.

For a later `/library` smoke test, authenticate through the page's admin-token
input (never a URL or browser localStorage), upload only one tracked synthetic
document at a time, inspect and retrieve its exact quote, update it, and delete
only that upload ID. Repeat for each supported format only after the four
format fixtures passed in the disposable database.

To inspect memory, open Render Logs and find `application_startup_memory` and
the per-request `investigation_memory` JSON records. Compare `peak_rss_bytes`
to `536870912` bytes (512 MiB); inspect `rss_growth_bytes` and
`peak_concurrent_investigations` for repeated and overlapping requests. Also
check Render's service memory graph. Startup RSS alone does not verify upload
or concurrent request memory safety.

## Local verification

```powershell
.\.venv\Scripts\python -m pytest -q
```

Result: **192 passed in 2.95s**. These tests are local automated tests, not
real PostgreSQL, production CRUD, or Render verification. The activation gate
remains pending a disposable database.
