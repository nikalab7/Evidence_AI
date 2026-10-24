# EvidenceAI structure

The project uses a small FastAPI application now and reserves packages for later
milestones. A folder existing in the tree does not mean its feature is complete.

```text
app/
  main.py, config.py
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
scripts/        dataset and database utilities (placeholders)
eval/           versioned evaluation cases (future)
tests/          automated tests
reports/        sanitized probes and AI usage disclosure
docs/           public technical requirements, roadmap, and architecture
```

Current request path: client -> FastAPI app -> health router -> JSON response. The
health route checks process liveness only; the Gemini and database probes are
explicit diagnostic commands and are not run on each health request. No document
ingestion or investigation route is implemented yet.
