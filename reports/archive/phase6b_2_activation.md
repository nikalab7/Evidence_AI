# Phase 6B.2 — Activation and Render Handoff

## Database migration: operator-reported complete

The operator reports that migration `20261025133854` (`phase6b_managed_uploads`)
was applied to Frankfurt EvidenceAI project `nldnpqhqrfwjgxcqeuru`. The operator
reports the following **after** values and checks:

| Check | Operator-reported result |
|---|---:|
| PostgreSQL | 17.11 |
| `documents` | 50,000 |
| `document_sources` | 50,018 |
| `chunks` | 50,000 |
| `managed_uploads` | 0 |
| RLS | Enabled |
| `anon` / `authenticated` SELECT | None |
| `service_role` | CRUD confirmed |
| Composite source/document FK | Confirmed |
| Supporting unique index | Confirmed |

These are owner-provided results, not checks performed by Codex. There was no
connected Supabase database tool in this session, so I did not reconnect to the
project, rerun the migration, query row counts, or independently verify grants,
indexes, search objects, backup, or storage. No production database records
were changed by Codex. Mindo, Sydney, and the held-out evaluation data were not
accessed.

The migration file remains
`migrations/proposals/phase6b_managed_uploads.sql`. Do not run it again. The
application is not deployed or live-tested against the new table.

## Application and configuration review

The local application provides `GET /library` and admin-protected
`/api/documents` list, inspect, upload, replace, and delete routes. The API
rejects an `ADMIN_TOKEN` shorter than 32 characters and uses
`hmac.compare_digest`; the browser keeps the token in page memory rather than
local storage. Local automated tests exercise the routes and management logic,
but no live Render request was made. There is no Render connector in this
session, so the presence and length of the live token could not be verified.

The Frankfurt Blueprint previously hardcoded
`INVESTIGATION_DAILY_BUDGET=0`, which would disable investigations and risk
overwriting the operator's positive value. The Blueprint now declares that
setting as `sync: false`, like `DATABASE_URL`, `GEMINI_API_KEY`, and
`ADMIN_TOKEN`. This leaves those values for the Dashboard: on Blueprint updates
Render ignores `sync: false` variables, preserving manually configured values;
on initial Blueprint creation the operator must provide them. This changes no
live Render setting. A regression test protects the manual budget/secret
configuration.

Render has not been deployed. On the Frankfurt service, verify the positive
investigation budget is present, do not replace `DATABASE_URL` or
`GEMINI_API_KEY`, and ensure `ADMIN_TOKEN` is a server-side secret of at least
32 characters without displaying or logging it. The owner must perform this
check in Render.

## Manual Render deployment

Use the Frankfurt service `evidence-ai-frankfurt` from
`render.frankfurt.yaml`. Confirm its region is Frankfurt and auto-deploy is
off. After this documentation/configuration commit is pushed, use its exact SHA
from the delivery message in **Deploys → Manual Deploy → Deploy a specific
commit**. Do not sync Blueprint settings until the Dashboard confirms the
positive `INVESTIGATION_DAILY_BUDGET` and existing secrets are preserved. For a
new Blueprint, set a positive budget and enter the secrets as masked values.

```text
Build: pip install -r requirements.txt && python scripts/download_model.py
Start: uvicorn app.main:app --host 0.0.0.0 --port $PORT --no-proxy-headers
Health check: /health
```

Keep these environment variable names configured:
`PYTHON_VERSION`, `ENABLE_EMBEDDING_STARTUP_CHECK`, `FASTEMBED_MODEL`,
`GEMINI_MODEL`, `INVESTIGATION_DAILY_BUDGET`,
`INVESTIGATION_PER_IP_PER_MINUTE`, `INVESTIGATION_MAX_CONCURRENT`,
`INVESTIGATION_TIMEOUT_SECONDS`, `GEMINI_REQUEST_TIMEOUT_SECONDS`,
`GEMINI_MAX_OUTPUT_TOKENS`, `DATABASE_STATEMENT_TIMEOUT_MS`,
`INDEXED_DOCUMENT_COUNT`, `DATABASE_URL`, `GEMINI_API_KEY`, and `ADMIN_TOKEN`.
Render supplies `PORT`. Do not change the existing database URL, Gemini key,
or positive daily investigation budget.

After deployment, inspect build logs for the offline model cache check, verify
`GET /health` returns 200, then run the smoke test below. Render supports
manual deployment of a specific commit; see [Render deployment
documentation](https://render.com/docs/deploys). Render documents that
`sync: false` values are ignored on later Blueprint updates, preserving the
Dashboard value; see [Blueprint environment variables](https://render.com/docs/blueprint-spec#environment-variables).

## Minimal post-deployment TXT smoke test

Use only a newly created, unique synthetic TXT document:

1. Open `/health` and confirm HTTP 200; open `/library`.
2. Authenticate with the admin token in the page. Do not put it in a URL or
   browser local storage.
3. Upload a small TXT file containing a unique fact; record its upload ID and
   content-addressed document ID.
4. Ask an investigation question answered by that file. Confirm retrieval
   returns the document and the citation quote matches the text exactly.
5. Replace the file with different unique text. Confirm its content-addressed
   document ID changes and the new fact is retrievable.
6. Delete only the recorded synthetic upload. Confirm it is absent from the
   library and its test fact is no longer retrieved.
7. Confirm the test upload left no `managed_uploads` record and that the
   original corpus counts remain 50,000 / 50,018 / 50,000. Do not modify any
   original corpus document.
8. In Render Metrics, inspect peak memory during the upload and compare it to
   512 MiB (`536870912` bytes). The app logs startup RSS and investigation RSS,
   but do not infer upload RSS from those logs; use the Render memory graph for
   the upload interval.

Stop on any unexpected result. Do not run cleanup against corpus data.

## Local verification and remaining limits

The full local suite was run with:

```powershell
.\.venv\Scripts\python -m pytest -q
```

Result: **194 passed in 2.98s**. Local tests are not production verification.
Still unverified by Codex: the operator-reported
Supabase migration results, live Render region and environment values, live
admin-token length, application startup against the migrated schema,
upload/retrieval CRUD, and Render memory under upload load. Do not begin Phase 7
until the operator smoke test is complete.
