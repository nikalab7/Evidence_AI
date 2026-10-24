# Supabase and Render Region Migration

Date: 2026-10-25
Status: **blocked before database changes**

## Identity and read-only preflight

The local `DATABASE_URL` parses to Supabase project reference
`nldnpqhqrfwjgxcqeuru` and host `aws-1-eu-central-1.pooler.supabase.com`.
This differs from both the Mindo project (`umbayvfikvxjzhxojofn`) and the
Sydney Evidence_AI fallback (`csenhlrsttuukzwglttf`). The endpoint identifies
the configured target as the Frankfurt-region pooler. The application guard
now allows only this configured project reference.

A TLS connection attempt reached the pooler but PostgreSQL rejected password
authentication. No authenticated database session was established. Therefore
the database identity, public relation inventory, SELECT latency, schema state,
and data state could not be verified. No schema SQL, ingestion, or other DB
write was run. Mindo and Sydney were not connected to or modified.

## Latency comparison

| Measurement | Sydney workstation baseline | Frankfurt workstation result |
| --- | ---: | --- |
| Connection establishment | 2.4963 s (one sample) | Not measured; authentication failed |
| `SELECT 1` round trip | 0.8106 s (one sample) | Not measured; no session |
| Variability | Baseline had one sample per measure | Not measurable |

No latency improvement is claimed. After fixing the Frankfurt database
credentials, repeat multiple fresh connections and repeated `SELECT 1` calls
before applying schema or importing the corpus. The existing baseline is small
and is not a guarantee of future latency.

## Database migration gate

Not run: public-schema inventory; `pgvector` setup; optimized Phase 1E schema;
1,000-document reload; four-thread embedding run; post-load HNSW build; count,
relationship, vector-dimension, reconstruction, evidence-coverage, idempotence,
security, retrieval, and full-investigation checks; storage measurements.

The Sydney Evidence_AI project remains the fallback. Mindo remains strictly
untouched. No database tables were dropped, recreated, or written.

## Render preparation

`render.yaml` remains unchanged for the existing `evidence-ai` service.
`render.frankfurt.yaml` defines a separate `evidence-ai-frankfurt` service in
Frankfurt, with automatic deploys off and secret values configured manually.
It has not been created or deployed. In the Render Dashboard, create a **new
Blueprint** from the same repository and select `render.frankfurt.yaml` as the
Blueprint path; then confirm the new service name and Frankfurt region before
creating it. Set `DATABASE_URL` and `GEMINI_API_KEY` in the new service's secret
environment settings. Verify its redacted project reference before deploying.

Render documents that a service's region cannot be changed after creation, and
that deploying in another region requires creating a new service. The existing
Sydney service must remain in place during this process.

## Required next action

In the Frankfurt Supabase Dashboard, copy the database connection URI for the
new project's database (or reset its database password and update the URI).
Update only the local `.env` value; do not paste the credential into chat or
commit it. Then rerun the read-only identity, table-inventory, and latency gate.
Proceed with the 1,000-document migration only if the authenticated identity is
the expected Frankfurt project, `public` has no unexpected relations, and the
measured latency meets the project's improvement gate.
