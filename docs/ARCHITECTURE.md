# EvidenceAI structure

The project uses a small FastAPI application now and reserves packages for later
milestones. A folder existing in the tree does not mean its feature is complete.

```text
app/
  main.py             FastAPI entry point
  config.py           Environment configuration; secrets are never printed
  api/                HTTP routes; currently only GET /health
  db/                 PostgreSQL/Supabase access, future
  ingestion/          Parsing, chunking, deduplication, indexing, future
  retrieval/          Semantic, keyword, and hybrid search, future
  llm/                Gemini client, tools, investigation flow, future
  reasoning/          Citation checks and abstention, future
  evaluation/         Metrics and evaluation runner, future
  templates/          Server-rendered HTML, future
  static/             CSS and browser assets, future
migrations/           Database schema changes, future
scripts/              Dataset and database utilities, future
eval/                 Versioned evaluation cases, future
tests/                Automated tests
reports/              Sanitized project evidence and AI usage disclosure
```

Current request path: client → FastAPI app → health router → JSON response. The
health route checks process liveness only; the Gemini and database probes are
explicit diagnostic commands and are not run on each health request. No document
ingestion or investigation route is implemented yet.
