# EvidenceAI

A Python-based investigation engine for finding, connecting, and citing evidence across documents. The codebase is organized by responsibility so each subsystem can be implemented and tested in its own milestone.

## Current status

Phase 0 through Phase 6A are implemented, including the staged 50,000-document Frankfurt corpus, multi-step Gemini investigation, citation validation, and retrieval tuning. Phase 6B document upload and management code is prepared locally. Its additive ownership-table migration is proposal-only; it has not been applied, and no live database write or production deployment was performed. The latest ingestion and capacity evidence is in [`reports/capacity_50k.md`](reports/capacity_50k.md); retrieval comparisons are in [`reports/retrieval_tuning_50k.md`](reports/retrieval_tuning_50k.md). The 200-question development set is the tuning dataset; the separate 40 candidates remain held out.

The single-service FastAPI application serves the investigation page and `POST /api/investigate`. Investigations use semantic retrieval by default; keyword and hybrid modes remain selectable. The API uses the existing four-step/five-HTTP-request agent and strips internal traces from public responses. The app includes process-local IP, concurrency, and daily-budget protection. The checked-in `INVESTIGATION_DAILY_BUDGET=0` remains the fail-closed default; the owner reports that the live service is configured for 10 investigations/day. These in-memory limits reset on process restart and are not a durable global quota.

The owner has shared a successful live multi-hop answer for a question connecting Cyma Watches with Universal Genève. This demonstrates one reported public investigation, but Render deployment details, the corresponding memory log, quota availability, and repeated-request RSS behavior have not been independently verified in this workspace. See the [interview demo](docs/INTERVIEW_DEMO.md) and [Phase 4A.1 report](reports/phase4a_1_production_validation.md).

## Interview demo: two-source investigation

**Question:** “The company that oversees Cyma Watches was founded when?”

The owner-shared live response answers **1894** and cites two retrieved chunks: one connects Cyma Watches to Universal Genève; the other says Universal Genève was founded in 1894. The exact quotations and chunk IDs are in [`docs/INTERVIEW_DEMO.md`](docs/INTERVIEW_DEMO.md). The request's Render `investigation_memory` event is still needed to compare its latency and memory with the earlier simple question.

## Project structure

```text
evidence-ai/
├── app/
│   ├── __init__.py
│   ├── main.py                 FastAPI entry point
│   ├── lifespan.py             Shared model/client lifetime and startup RSS
│   ├── memory_monitor.py       Sampled per-investigation process RSS
│   ├── rate_limit.py           Atomic process-local request budgets
│   ├── embedding_smoke.py      FastEmbed dimensions, timing, and RSS
│   ├── model_cache.py          Offline FastEmbed cache loader
│   ├── config.py               Environment configuration
│   ├── api/
│   │   ├── health.py           Working liveness route
│   │   ├── documents.py        Admin-authenticated document CRUD API
│   │   ├── investigations.py   Validated investigation API
│   │   └── pages.py            Server-rendered public interface
│   ├── db/
│   │   ├── connection.py       TLS psycopg connection from environment settings
│   │   └── queries.py          Parameterized ingestion, retrieval, verification, and size queries
│   ├── ingestion/
│   │   ├── corpus_core.py       Text normalization and evidence coverage
│   │   ├── corpus_store.py      Content hashes, aliases, and collision stats
│   │   ├── corpus_selection.py  Fixed-seed stratified question selection
│   │   └── hotpotqa_corpus.py   Local pinned corpus build and audit
│   │   ├── parsers.py           Bounded PDF, DOCX, TXT, and Markdown parsing
│   │   ├── chunkers.py          Paragraph and fixed-overlap offset strategies
│   │   ├── managed_documents.py Transactional upload/index service
│   │   ├── deduplication.py     Stable document, source, and chunk IDs
│   │   └── indexer.py            Metadata preparation and local embeddings
│   ├── retrieval/
│   │   ├── engine.py            Shared semantic/keyword/hybrid interface
│   │   ├── semantic.py          BGE + pgvector cosine retrieval
│   │   ├── keyword.py           PostgreSQL FTS retrieval
│   │   └── ranker.py            Weighted Reciprocal Rank Fusion
│   ├── llm/
│   │   ├── gemini_client.py     Bounded Gemini REST client
│   │   ├── agent.py             Four-step evidence investigation loop
│   │   ├── tools.py             Read-only semantic/keyword/hybrid tools
│   │   └── schemas.py           Structured request and response schemas
│   ├── reasoning/
│   │   ├── citations.py         Retrieved-chunk and exact-quote validation
│   │   └── abstention.py        Insufficient-evidence response
│   ├── evaluation/
│   │   ├── metrics.py           Evidence-gated Recall@K and MRR
│   │   └── run.py               Placeholder
│   ├── templates/
│   │   ├── library.html         Authenticated Document Library
│   │   └── investigate.html     Responsive investigation interface
│   └── static/                  Inline page styling and behavior
├── migrations/schema.sql        Additive documents, provenance, chunks, FTS, and vector schema
├── migrations/proposals/        Phase 6B ownership-table migration proposal
├── scripts/
│   ├── audit_hotpotqa.py       Streaming uniqueness/evidence audit
│   ├── build_corpus.py          Local corpus selection and coverage report
│   ├── download_model.py        Render build-time FastEmbed cache
│   ├── ingest_hotpotqa.py       Staged Supabase ingestion CLI capped at 50,000 documents
│   ├── retrieve.py              Natural-language semantic/keyword/hybrid CLI
│   ├── evaluate_retrieval.py    Evidence-gated real Supabase retrieval evaluation
│   ├── compare_chunking.py      Local synthetic chunking/retrieval comparison
│   └── measure_db_size.py       Read-only database/table size and row counts
├── tests/                       Automated tests
├── eval/                         Retrieval dev and eval candidate cases
├── reports/                     Sanitized service evidence and AI usage report
├── docs/                         Public requirements, roadmap, architecture
├── AGENTS.md                     Project-specific coding instructions
├── requirements.txt
├── requirements-dev.txt
├── requirements-audit.txt       Optional local-only dataset audit dependency
├── .env.example
└── .gitignore
```

`Dockerfile` will be added with the deployment milestone. The original assessment copy, detailed personal plan, and interview notes stay local and are ignored by Git. See `docs/ARCHITECTURE.md`, `docs/PROJECT_REQUIREMENTS.md`, and `docs/IMPLEMENTATION_ROADMAP.md` for the project-facing documentation.

## HotpotQA corpus audit

The audit streams a pinned HotpotQA revision and writes aggregate uniqueness and
supporting-evidence counts. It does not write raw rows to Git or Supabase. The
recorded full scan is in [`reports/hotpotqa_audit.json`](reports/hotpotqa_audit.json);
method and reproduction steps are in [`docs/HOTPOTQA_AUDIT.md`](docs/HOTPOTQA_AUDIT.md).

```powershell
python -m pip install -r requirements-audit.txt
python -m scripts.audit_hotpotqa --max-rows 100 --output "$env:TEMP\hotpotqa-audit-smoke.json"
python -m scripts.audit_hotpotqa --output reports\hotpotqa_audit.json
```

The source-pool scan found 507,494 title-plus-paragraph records across train
and validation. The fixed-seed content-hash subset has been materialized: the
200-question retrieval set is committed; the reproducible 50,000-record source
corpus remains local and Git-ignored. The Frankfurt database reached 50,000
documents in the approved staged run. Recorded counts, sizes, and limits are in
`reports/capacity_50k.md`.

The selected local subset and its reproducibility record are in
[`reports/corpus_audit.json`](reports/corpus_audit.json). Sampling and identity
rules are documented in [`docs/HOTPOTQA_CORPUS_BUILD.md`](docs/HOTPOTQA_CORPUS_BUILD.md).
The default builder writes the report and 40 candidate questions; use
`--write-large-files` to regenerate the 200-question retrieval set and local
50,000-record corpus.

## Local setup (PowerShell, Python 3.11+)

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
# Copy the template only if you do not already have your .env.
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python -m uvicorn app.main:app --reload
```

The server runs at `http://127.0.0.1:8000`; `GET /` serves investigations, `GET /library` serves the Document Library, `POST /api/investigate` runs an investigation, and `GET /health` returns `{"status":"ok"}`. Health checks process liveness only. For local investigations, set a small positive `INVESTIGATION_DAILY_BUDGET` only after checking the configured Gemini project's quota. The default value `0` intentionally disables the API.

Keep real credentials in `.env`, which Git ignores. `.env.example` contains names only. `connect_database()` refuses Supabase URLs that do not identify project `nldnpqhqrfwjgxcqeuru`; keep `DATABASE_URL` backend-only and configure the Frankfurt URI as a secret on the new Render service before deployment. `render.frankfurt.yaml` defines the separate service; the existing service is not replaced.

## Phase 6B: document uploads and management

The Document Library supports text-based PDF, DOCX, UTF-8 TXT, and Markdown
uploads. Scanned/image-only PDFs are rejected with an OCR-required message.
Uploads are limited to 5 MiB, extracted text to 200,000 characters, PDFs to 200
pages, and DOCX packages to 20 MiB expanded size. Paragraph chunks and 1,000-
character chunks with 150-character overlap both preserve offsets into the
canonical text.

All `/api/documents` routes, including list and inspect, require
`Authorization: Bearer <ADMIN_TOKEN>`. The token stays only in the open page's
memory and is cleared when the library is locked or the page closes. It is not
written to browser storage or included in a URL. Configure a random token of at
least 32 characters in `.env` locally and as a secret environment variable on
Render. The example template intentionally leaves it blank.

Content IDs are normalized text hashes. Identical content already in the index
is rejected without adding upload ownership; replacement creates a new ID for
changed content rather than editing text under the old ID. Upload provenance is
recorded separately, and delete removes only that upload's provenance. A
document still referenced by another source is retained. New chunks use the
existing embeddings, FTS trigger, and semantic/keyword/hybrid queries, so the
50,000-document corpus is not reindexed.

Before the library can use Supabase, review and explicitly approve
[`migrations/proposals/phase6b_managed_uploads.sql`](migrations/proposals/phase6b_managed_uploads.sql)
and apply it manually to the Frankfurt Evidence_AI project. The application
never runs this migration at startup. Do not deploy or write to production
until the owner has approved and applied that additive migration and configured
`ADMIN_TOKEN`. The local tests use fixtures and fakes; they do not verify live
schema, database CRUD, or Render behavior.

Run the local strategy comparison with:

```powershell
.\.venv\Scripts\python -m scripts.compare_chunking
```

It reads only a small synthetic fixture, loads BGE from the local cache without
network access, and reports semantic Recall@1/MRR for three fixture queries.
This is a reproducibility check, not a corpus-quality estimate. Results and
memory/safety notes are in [`reports/document_ingestion.md`](reports/document_ingestion.md).

## Service probes

```powershell
.\.venv\Scripts\python -m app.service_probe --output reports/service_probe.json
.\.venv\Scripts\python -m app.service_probe --only database --enable-vector --output reports/database_probe.json
```

The first command lists available generation models and makes at most one small Gemini request. The second checks Supabase and `pgvector` without spending Gemini quota. Reports omit credentials and raw service error bodies. Refer to the Phase 5 report for measured 50K capacity rather than treating a general service probe as a capacity test.

The older database probe describes the Mindo project and is historical. EvidenceAI uses its Frankfurt project. Actual 50K row counts, sizes, and indexes are recorded in [`reports/capacity_50k.md`](reports/capacity_50k.md); Frankfurt retrieval results are in [`reports/retrieval_tuning_50k.md`](reports/retrieval_tuning_50k.md). The earlier Render FastEmbed startup measurement is a baseline only; it does not establish memory safety for live investigations.

## Render embedding preflight

`render.frankfurt.yaml` configures a distinct Frankfurt Python web service,
preloads the FastEmbed cache at build time, then starts FastAPI with Uvicorn
proxy-header rewriting disabled. Rate limiting uses the
Cloudflare-provided `CF-Connecting-IP`, not client-supplied `X-Forwarded-For`.
On each process start the app logs sanitized RSS after model initialization.
Each active investigation also logs before/after RSS, a 50 ms sampled peak,
and peak concurrent requests.
The startup number alone is not a memory safety result; measure three real
requests and a two-request overlap on the deployed service. Swagger and OpenAPI
routes are disabled.

The build command runs `scripts/download_model.py` into `.model_cache/` and
verifies offline loading. Runtime uses that same cache with
`local_files_only=True`, so a missing model fails startup instead of downloading.
The public page includes the free-hosting cold-start notice; it cannot appear
until the server has responded with the initial HTML.

The Frankfurt Blueprint has automatic deploys disabled. Its checked-in daily
budget default is `0`, which disables investigation requests; the owner reports
that the deployed service has a positive 10/day setting. Verify the live
settings before syncing the Blueprint, since syncing may replace the live
value. The owner-shared answer demonstrates one successful public request, but
startup/request RSS, the actual deployed commit and service configuration, and
repeated/concurrent request measurements remain pending Render log review. The
previous embedding preflight is documented in
[reports/render_preflight.md](reports/render_preflight.md); earlier gates are
in [reports/phase4a_web_app.md](reports/phase4a_web_app.md) and the latest
evidence is in [reports/phase4a_1_production_validation.md](reports/phase4a_1_production_validation.md).

An exact quote match shows that text occurs in a source; factual entailment requires a separate check.
