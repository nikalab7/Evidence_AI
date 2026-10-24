# EvidenceAI structure

The project uses a small FastAPI application now and reserves packages for later
milestones. A folder existing in the tree does not mean its feature is complete.

```text
app/
  main.py, config.py, lifespan.py, embedding_smoke.py
  api/          health.py (working); documents.py, investigations.py (placeholders)
  db/           connection.py, queries.py (placeholders)
  ingestion/    parsers.py, chunkers.py, deduplication.py, indexer.py (placeholders)
  retrieval/    semantic.py, keyword.py, ranker.py (placeholders)
  llm/          gemini_client.py, agent.py, tools.py, schemas.py (placeholders)
  reasoning/    citations.py, abstention.py (placeholders)
  evaluation/   metrics.py, run.py (placeholders)
  templates/    library.html, investigate.html (static notices only)
  static/       CSS and browser assets (future)
migrations/     schema.sql (documentation placeholder; no schema applied)
scripts/        audit_hotpotqa.py (working read-only audit); ingestion and database utilities (placeholders)
eval/           versioned evaluation cases (future)
tests/          automated tests
reports/        sanitized probes and AI usage disclosure
docs/           public technical requirements, roadmap, and architecture
```

Current request path: client -> FastAPI app -> health router -> JSON response. The
health route checks process liveness only. The Render startup check loads one
FastEmbed model and logs aggregate measurements; it is not an HTTP diagnostics
route. Gemini and database probes remain explicit commands. The HotpotQA audit
streams public data locally and writes aggregate results, but no document
ingestion or investigation route is implemented yet.
