# EvidenceAI

Multi-hop RAG investigation engine for evidence-based answers across documents.
Planned architecture: FastAPI/Jinja2, Supabase/Postgres FTS + pgvector, fastembed
bge-small-en-v1.5, Gemini tool calling, Render deployment.

Current status: **foundation and service diagnostics implemented; application
pipeline is not implemented yet.** Gemini generation and Supabase/vector probes
passed. Sanitized service evidence is in `reports/service_probe.json`
and `reports/database_probe.json`. No documents have been ingested.

## Local setup (PowerShell, Python 3.11+)

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
# Only if .env does not already exist:
Copy-Item .env.example .env
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python -m app.preflight
```

Fill `.env` locally. Never commit credentials. The verified Gemini model is
recorded in `.env`; environment variables override local `.env` values.
The readiness command prints names/statuses, never credential values. Exit code 1
means ingestion is not cleared; this is the expected result at this milestone.
It inventories prerequisites and does not make network calls or ingest documents.

## Remaining implementation

1. Audit candidate dataset uniqueness and evaluation supporting evidence, including sentence coverage and split separation.
2. Measure actual Render RAM/latency with the intended embedding model; then the 100-document vertical slice.
3. Stage 1k and 10k loads and measure database/index size before approving 50k.

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
