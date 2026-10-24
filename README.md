# EvidenceAI

A Python-based investigation engine for finding, connecting, and citing evidence across documents. The codebase is organized by responsibility so each subsystem can be implemented and tested in its own milestone.

## Current status

The Phase 0 foundation and the verified 100-document Phase 1C ingestion slice are complete. Supabase contains 100 content-addressed documents, 100 provenance rows, and 100 paragraph chunks with 384-dimensional BGE embeddings. The selected 50,000-record corpus is generated locally; only the 100-document slice has been ingested. Full-scale capacity, 1,000-document ingestion, retrieval, RAG, document APIs, and the user-facing demo remain incomplete. The prior Render baseline is recorded, but a post-cache Render deployment/restart check remains pending. See [`reports/ingestion_100.md`](reports/ingestion_100.md).

## Project structure

```text
evidence-ai/
├── app/
│   ├── __init__.py
│   ├── main.py                 FastAPI entry point
│   ├── lifespan.py             Optional startup-only embedding smoke check
│   ├── embedding_smoke.py      FastEmbed dimensions, timing, and RSS
│   ├── model_cache.py          Offline FastEmbed cache loader
│   ├── config.py               Environment configuration
│   ├── api/
│   │   ├── health.py           Working liveness route
│   │   ├── documents.py        Placeholder
│   │   └── investigations.py   Placeholder
│   ├── db/
│   │   ├── connection.py       TLS psycopg connection from environment settings
│   │   └── queries.py          Parameterized ingestion, verification, and size queries
│   ├── ingestion/
│   │   ├── corpus_core.py       Text normalization and evidence coverage
│   │   ├── corpus_store.py      Content hashes, aliases, and collision stats
│   │   ├── corpus_selection.py  Fixed-seed stratified question selection
│   │   └── hotpotqa_corpus.py   Local pinned corpus build and audit
│   │   ├── parsers.py           Placeholder for file-upload ingestion
│   │   ├── chunkers.py          Paragraph chunker for Phase 1C
│   │   ├── deduplication.py     Stable document, source, and chunk IDs
│   │   └── indexer.py            Metadata preparation and local embeddings
│   ├── retrieval/
│   │   ├── semantic.py          Placeholder
│   │   ├── keyword.py           Placeholder
│   │   └── ranker.py            Placeholder
│   ├── llm/
│   │   ├── gemini_client.py     Placeholder; service probe is separate
│   │   ├── agent.py             Placeholder
│   │   ├── tools.py             Placeholder
│   │   └── schemas.py           Placeholder
│   ├── reasoning/
│   │   ├── citations.py         Placeholder
│   │   └── abstention.py        Placeholder
│   ├── evaluation/
│   │   ├── metrics.py           Placeholder
│   │   └── run.py               Placeholder
│   ├── templates/
│   │   ├── library.html         Static notice
│   │   └── investigate.html     Static notice
│   └── static/                  Future CSS and JavaScript
├── migrations/schema.sql        Additive documents, provenance, chunks, FTS, and vector schema
├── scripts/
│   ├── audit_hotpotqa.py       Streaming uniqueness/evidence audit
│   ├── build_corpus.py          Local corpus selection and coverage report
│   ├── download_model.py        Render build-time FastEmbed cache
│   ├── ingest_hotpotqa.py       Capped 100-document Supabase ingestion CLI
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
200-question retrieval set is committed, and the 50,000-document corpus remains
local and Git-ignored. Exactly 100 corpus records are currently in Supabase;
larger staged loads and capacity projections remain open.

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

The server runs at `http://127.0.0.1:8000`; `GET /health` returns `{"status":"ok"}`. The health endpoint checks only that the API process responds. It does not claim Gemini or database health.

Keep real credentials in `.env`, which Git ignores. `.env.example` contains names only. The local `app.preflight` command lists remaining gates and exits with code 1 while full ingestion is not cleared.

## Service probes

```powershell
.\.venv\Scripts\python -m app.service_probe --output reports/service_probe.json
.\.venv\Scripts\python -m app.service_probe --only database --enable-vector --output reports/database_probe.json
```

The first command lists available generation models and makes at most one small Gemini request. The second checks Supabase and `pgvector` without spending Gemini quota. Reports omit credentials and raw service error bodies. A successful connection and current database size do not prove that 50,000 records will fit.

The latest recorded probes show Gemini generation working with `gemini-3.5-flash-lite` and Supabase with `pgvector` 0.8.0. The database was 20,491,411 bytes before Phase 1C and measured 22,195,347 bytes after the 100-document slice and idempotence check; see [`reports/ingestion_100.md`](reports/ingestion_100.md) for the measured size change and row counts. Render's baseline FastEmbed startup check passed with a 384-dimensional vector and 300,912,640 bytes peak process RSS; a new Render build/restart check remains pending. Supabase full-scale capacity and final evaluation cases remain open. See the reports in `reports/`.

## Render embedding preflight

`render.yaml` configures a minimal Python web service and a startup-only
FastEmbed check. On each process start it loads `BAAI/bge-small-en-v1.5`, embeds
one query, and writes dimensions, load time, query latency, and process RSS to
service logs. `/health` remains a cheap liveness check; model measurements are
not exposed by an HTTP route. Swagger and OpenAPI routes are disabled.

The build command runs `scripts/download_model.py` into the project-local
`.model_cache/` directory and verifies a second model load with network access
disabled. Runtime uses that same cache with `local_files_only=True`, so a missing
model fails startup instead of downloading unexpectedly. The current build
script and a local lifespan startup with `/health` returned 200; verify the new
artifact and startup log after manually deploying the Blueprint to Render.

Create a Blueprint from this repository in Render to run the preflight. No
Gemini or Supabase secret is required for this isolated check. Render's Free
filesystem is ephemeral. The model cache is included by the build step in the
deployed artifact; runtime does not fetch model files after a restart or
spin-down.
Automatic deploys are disabled in the Blueprint; start the first deployment
from Render, then use the same service's restart action for the second check.
The actual Render startup measurements, local baseline, and pending restart
check are recorded in [reports/render_preflight.md](reports/render_preflight.md).

An exact quote match shows that text occurs in a source; factual entailment requires a separate check.
