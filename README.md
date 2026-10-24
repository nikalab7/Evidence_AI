# EvidenceAI

A Python-based investigation engine for finding, connecting, and citing evidence across documents. The codebase is organized by responsibility so each subsystem can be implemented and tested in its own milestone.

## Current status

The Phase 0 foundation includes environment configuration, live service probes, a FastAPI application, `GET /health`, and a Render startup-only FastEmbed check. The supplied Render log confirms 384 dimensions, 100.3 ms query embedding, and 300,912,640 bytes peak process RSS; the recorded Render memory gate is verified. A post-cache Render deployment/restart check remains pending. The local corpus audit found 50,000 unique content records with full selected-evidence coverage, but the two large JSONL outputs remain deferred. No records have been inserted into Supabase. Retrieval, RAG, document APIs, and the user-facing demo are not implemented.

## Project structure

```text
evidence-ai/
├── app/
│   ├── __init__.py
│   ├── main.py                 FastAPI entry point
│   ├── lifespan.py             Optional startup-only embedding smoke check
│   ├── embedding_smoke.py      FastEmbed dimensions, timing, and RSS
│   ├── model_cache.py          Shared build/runtime model cache verification
│   ├── config.py               Environment configuration
│   ├── api/
│   │   ├── health.py           Working liveness route
│   │   ├── documents.py        Placeholder
│   │   └── investigations.py   Placeholder
│   ├── db/
│   │   ├── connection.py       Placeholder; service probe is separate
│   │   └── queries.py           Placeholder
│   ├── ingestion/
│   │   ├── corpus_core.py       Text normalization and evidence coverage
│   │   ├── corpus_store.py      Content hashes, aliases, and collision stats
│   │   ├── corpus_selection.py  Fixed-seed stratified question selection
│   │   └── hotpotqa_corpus.py   Local pinned corpus build and audit
│   │   ├── parsers.py           Placeholder
│   │   ├── chunkers.py          Placeholder
│   │   ├── deduplication.py     Placeholder
│   │   └── indexer.py            Placeholder
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
├── migrations/schema.sql        Documentation placeholder; not applied
├── scripts/
│   ├── audit_hotpotqa.py       Streaming uniqueness/evidence audit
│   ├── build_corpus.py          Local corpus selection and coverage report
│   ├── download_model.py        Render build-time FastEmbed cache
│   ├── ingest_hotpotqa.py       Placeholder
│   └── measure_db_size.py       Placeholder
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
and validation. Content-hash subset selection is now audited separately;
materializing its large JSONL files and measuring Supabase staged capacity
remain open. No database ingestion has started.

The selected local subset and its reproducibility record are in
[`reports/corpus_audit.json`](reports/corpus_audit.json). Sampling and identity
rules are documented in [`docs/HOTPOTQA_CORPUS_BUILD.md`](docs/HOTPOTQA_CORPUS_BUILD.md).
The default builder writes only the report and 40 candidate questions; it needs
`--write-large-files` to create the 200-question retrieval set and local
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

The latest recorded probes show Gemini generation working with `gemini-3.5-flash-lite` and Supabase with `pgvector` 0.8.0. The database was 20,491,411 bytes before ingestion. Render's baseline FastEmbed startup check passed with a 384-dimensional vector and 300,912,640 bytes peak process RSS; a new Render build/restart check remains pending. The source-pool audit found 507,494 unique title-plus-paragraph records; the selected content-hash corpus separately contains 50,000 records with all selected evidence present. Supabase quota/capacity and final evaluation cases remain open. See the reports in `reports/`.

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
