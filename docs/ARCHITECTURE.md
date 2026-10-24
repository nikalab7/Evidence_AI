# EvidenceAI structure

The project uses a small FastAPI application and a local CLI path for the
verified 100-document ingestion milestone. A folder existing in the tree does
not mean its feature is complete.

```text
app/
  main.py, config.py, lifespan.py, embedding_smoke.py
  api/          health.py (working); documents.py, investigations.py (placeholders)
  db/           connection.py (psycopg); queries.py (parameterized ingestion and verification)
  ingestion/    chunkers.py, deduplication.py, indexer.py (100-document path); parsers.py (placeholder)
  retrieval/    semantic.py, keyword.py, ranker.py (placeholders)
  llm/          gemini_client.py, agent.py, tools.py, schemas.py (placeholders)
  reasoning/    citations.py, abstention.py (placeholders)
  evaluation/   metrics.py, run.py (placeholders)
  templates/    library.html, investigate.html (static notices only)
  static/       CSS and browser assets (future)
migrations/     schema.sql (additive documents, provenance, chunks, FTS, and pgvector schema)
scripts/        audit_hotpotqa.py; ingest_hotpotqa.py (capped at 100); measure_db_size.py
eval/           versioned evaluation cases (future)
tests/          automated tests
reports/        sanitized probes and AI usage disclosure
docs/           public technical requirements, roadmap, and architecture
```

Current request path: client -> FastAPI app -> health router -> JSON response. The
health route checks process liveness only. The Render startup check loads one
FastEmbed model and logs aggregate measurements; it is not an HTTP diagnostics
route. Gemini and read-only database probes remain explicit commands. A local
ingestion CLI embeds the first 100 unique corpus paragraphs and writes them to
Supabase through psycopg. It does not add an ingestion API or retrieval route;
Gemini answer generation and citations remain unimplemented.
