# EvidenceAI architecture and investigation flow

EvidenceAI is a Python FastAPI application backed by Frankfurt Supabase
PostgreSQL/pgvector, local FastEmbed query embeddings, and Gemini. The app and
interface are served by the same process. The live 50,000-document corpus is
read-only during investigation; this application path does not ingest or alter
records.

## HTTP surface

- `GET /` serves the responsive investigation page from
  `app/templates/investigate.html`.
- `POST /api/investigate` accepts a 3–1,000 character question and one of
  `semantic`, `keyword`, or `hybrid`. Semantic mode is the default based on the
  Phase 6A development-set comparison. Keyword and hybrid remain available for
  comparison and demonstration.
- `GET /health` returns process liveness only. It does not test Supabase or
  Gemini.
- `GET /library` serves the administrator document-management interface.
- `/api/documents` provides authenticated upload, list, inspect, replace, and
  delete operations; the original indexed corpus is not owner-managed.
- OpenAPI, Swagger, and ReDoc routes are disabled.

The page presents the 50,000-record corpus size, the free-hosting cold-start
notice, request progress, sanitized errors, citations, exact quotes, and clear
insufficient/conflicting states. User-controlled and model-produced strings
are inserted with DOM `textContent`; source links are restricted to HTTP(S).
The cold-start note is part of the HTML and cannot be seen until the server
responds with that initial page.

## Request lifecycle

```text
Browser
  -> FastAPI validation and body-size bound
  -> process-local IP/daily/concurrency admission checks
  -> worker thread: one fail-closed Frankfurt DB connection
  -> up to four Gemini-selected read tools / five HTTP attempts total
  -> semantic retrieval by default using the startup-loaded BGE model
  -> citation and exact-quote validation against retrieved chunk IDs
  -> public response containing verified claims and source evidence only
```

One `GeminiClient` and one FastEmbed model instance are loaded during the
application lifespan and reused across requests. Each investigation opens one
database connection and reuses it for its tool calls. A tool runs in a bounded
transaction with a PostgreSQL statement timeout; the transaction is closed
before the next Gemini HTTP request. The connection closes after the
investigation. This avoids sharing a psycopg connection concurrently and
prevents idle open transactions during model calls.

Semantic retrieval embeds Gemini's focused search query. When that query or
the original user question contains a high-confidence exact title or identifier
and no matching title alias appears in the semantic results, the retriever runs
a bounded title-scoped semantic rescue. It considers at most three exact alias
references, refuses aliases matching more than 25 documents, and returns at
most three chunks ranked by cosine distance within the materialized candidates.
This avoids widening every query or relying on a global ANN shortlist to find a
newly uploaded document. If normal semantic results already contain the exact
title, their original order is preserved and no extra query runs.

The existing agent remains bounded at four investigation steps and five actual
Gemini HTTP attempts, including retries. Every request has a configurable
timeout and output-token cap. The API maps upstream/database failures to
generic public errors. Internal traces and diagnostic logs distinguish a
retrieval miss, model abstention, missing citations, rejected citations, and
verified citations using counts and status codes only; questions, document
titles/text, chunk IDs, API keys, and database URLs are not included in those
logs or public responses.

The existing two-level citation validator verifies that each cited chunk was
retrieved and that its quote is present verbatim after whitespace
normalization. Chunk text is reconstructed from canonical document text and
stored offsets. Unsupported claims are removed; if the central claim cannot be
verified, the agent abstains. Quote presence is not a factual-entailment test.

## Abuse limits and quota behavior

The API enforces a 16 KiB JSON body limit, strict question validation, a
per-IP rolling request limit, a rolling 24-hour investigation budget, and a concurrent
request cap. Reservations are atomic within a Python process; each admitted
investigation reserves one daily unit, even if it fails, because an upstream
request may already have consumed quota. An investigation may make up to five
Gemini HTTP requests.

The rolling 24-hour window is conservative against Gemini's daily reset at
midnight Pacific time; it does not require timezone data in the runtime.

These counters live only in process memory. They reset after restart/spin-down
and are not shared across multiple workers or instances. Therefore they are a
temporary safeguard, not a restart-proof global daily cap. The default
`INVESTIGATION_DAILY_BUDGET=0` fails closed and disables investigations until an
operator checks the actual Gemini project's model quota and configures a
conservative value. No Redis service or database table was provisioned. A
durable cap would require a separate approval for an atomic daily counter in
PostgreSQL or a managed shared store.

The per-IP key uses exactly one syntactically valid `CF-Connecting-IP` address.
The Frankfurt Render start command disables Uvicorn proxy-header rewriting;
the application ignores client-supplied `X-Forwarded-For`. If the Cloudflare
header is missing or malformed, the limiter falls back to the immediate socket
peer, which can group clients behind Render's proxy into one bucket. Render
documents Cloudflare as the inbound edge, and Cloudflare documents
`CF-Connecting-IP` as the visitor address it sends to the origin. This trust
assumption must be rechecked if the service's edge/proxy path changes.

## Memory and hosting

At startup, sanitized current and high-water process RSS are logged after the
embedding model is loaded. While investigations run, a background sampler
records per-request before/after RSS and a 50 ms sampled peak, including peak
concurrency. A short allocation can fall between samples, so the report labels
this as sampled RSS. The Render Free ceiling is 512 MiB; startup-only numbers
do not prove request-time memory safety. Three real consecutive investigations
and a two-request overlap must be measured from actual Render logs before that
gate can pass.

The Frankfurt blueprint uses a project-local FastEmbed cache downloaded at
build time and loaded offline at runtime. Render Free may spin down after
inactivity; the interface displays the requested cold-start note. This note
cannot display during the delay before the first HTML response.

## Data and evaluation boundaries

The approved Phase 5 run records 50,000 documents, 50,018 provenance rows, and
50,000 chunks; its measured storage and integrity evidence is in
`reports/capacity_50k.md`. The current investigation code does not write to
those tables. The 200-question retrieval development set is the sole set for
retrieval tuning. The 40 held-out evaluation candidates are not used by the
agent or this interface.

The dedicated Frankfurt Supabase project is
`nldnpqhqrfwjgxcqeuru`. Database connections fail closed unless the configured
Supabase URL identifies that project. Mindo and the former Sydney project are
not used by the application.

## Verification notes

Local API contract and scripted-agent tests exercise successful citation
validation and abstention over HTTP. They do not substitute for a live Gemini
quota check, live public Render request, Render memory measurement, or a
post-idle cold-start test. See `reports/archive/phase4a_web_app.md` for the exact
verified results and pending operator actions.
