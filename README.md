# EvidenceAI

Multi-hop RAG investigation engine for evidence-based answers across documents.
Planned architecture: FastAPI/Jinja2, Supabase/Postgres FTS + pgvector, fastembed
bge-small-en-v1.5, Gemini tool calling, Render deployment.

Current status: **Phase 0 skeleton.** FastAPI and `GET /health` are implemented.
Gemini generation and Supabase/pgvector connection probes passed. No documents
have been ingested; retrieval, RAG, UI, and deployment remain unimplemented.
See `docs/ARCHITECTURE.md` for the folder map and current request path.

## Local setup (PowerShell, Python 3.11+)

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
# Only if .env does not already exist:
Copy-Item .env.example .env
# Activate the isolated environment for future commands:
.\.venv\Scripts\Activate.ps1
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python -m uvicorn app.main:app --reload
```

The API starts at `http://127.0.0.1:8000`; `GET /health` returns
`{"status":"ok"}`. The project uses its small `Settings` loader in
`app/config.py`; no extra settings framework is needed for this skeleton.

Fill `.env` locally. Never commit credentials. The verified Gemini model is
recorded in `.env`; environment variables override local `.env` values.
`python -m app.preflight` prints readiness names/statuses, never credential
values. Exit code 1 means ingestion is not cleared; that is expected while gates
remain. It does not make network calls or ingest documents.

## Remaining implementation

1. Audit candidate dataset uniqueness and evaluation supporting evidence, including sentence coverage and split separation.
2. Measure actual Render RAM/latency with the intended embedding model before ingestion.
3. Implement ingestion milestones and test 100 → 1k → 10k before considering 50k.

Live service probe commands (use local `.env`; do not paste secrets into commands):

```powershell
python -m app.service_probe --output reports/service_probe.json
# Explicitly enable pgvector if available but not installed:
python -m app.service_probe --only database --enable-vector --output reports/database_probe.json
```

The probe makes at most one generation call; it does not retry quota errors.
`--only database` avoids another Gemini call when debugging credentials. Raw
database exceptions and API response bodies are excluded from evidence output.
The offline `app.preflight` inventory does not import live reports: use the
timestamped service JSON for actual service evidence. Neither command clears ingestion.

Gemini generation passed on 2026-10-24. After a configuration correction, the
Supabase probe passed the same day: pgvector 0.8.0 was enabled and a cosine
distance smoke query passed. Current total database size: 20,491,411 bytes,
before document ingestion. This baseline is not a 50k capacity measurement.
The database-only report is newer than the failed database attempt in the
combined service report. Dataset coverage, quota capacity, and Render RAM remain unverified.
Probe implementation follows the official [Gemini model listing](https://ai.google.dev/api/models)
and [content generation](https://ai.google.dev/api/generate-content) APIs.
An exact citation match establishes that quoted text exists; it cannot establish
that the text entails a claim. Factual entailment needs separate evaluation.

The repository contains application code, tests, configuration templates, and
technical documentation. Local credentials, development instructions, planning
documents, and interview notes are excluded by `.gitignore`.
