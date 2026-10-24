# AI usage report

Tool: OpenAI Codex. AI assistance is disclosed as a project deliverable.

## Implemented with AI assistance

- Python scaffolding and environment configuration.
- Readiness inventory and Gemini/PostgreSQL diagnostic probes.
- Tests for configuration precedence, ignored paths, HTTP errors, response
  validation, database failures, and secret-safe diagnostic output.
- Setup documentation and technical evidence reports.

## Validation and limitations

- Latest validation: `python -m pytest -q` — 27 passed in 0.23s.
- Live Gemini generation succeeded with `gemini-3.5-flash-lite`.
- PostgreSQL connection succeeded after a configuration correction; pgvector 0.8.0
  was enabled and a cosine smoke query passed. Baseline database size: 20,491,411
  bytes. Full dataset capacity remains unverified. See reports/database_probe.json.
- No ingestion, retrieval, ranking, citation validation, agentic loop, or deployed
  application is implemented. No evaluation-quality metrics are claimed.
- Independent non-AI implementation contributions are not recorded at this stage.

Local planning and personal preparation notes are excluded from the repository.
