# EvidenceAI structure and Phase 1E data path

The project uses a small FastAPI application and local CLI paths for the
verified 1,000-document ingestion and Phase 2 retrieval milestones. A folder existing in the tree does
not mean its feature is complete.

```text
app/
  main.py, config.py, lifespan.py, embedding_smoke.py
  api/          health.py (working); documents.py, investigations.py (placeholders)
  db/           connection.py (psycopg); queries.py (parameterized ingestion, retrieval, and metrics)
  ingestion/    chunkers.py, deduplication.py, indexer.py (1,000-document path); parsers.py (placeholder)
  retrieval/    engine.py, semantic.py, keyword.py, ranker.py (working CLI retrieval path)
  llm/          gemini_client.py, agent.py, tools.py, schemas.py (placeholders)
  reasoning/    citations.py, abstention.py (placeholders)
  evaluation/   metrics.py (evidence-gated Recall@K/MRR); run.py (final QA evaluation placeholder)
  templates/    library.html, investigate.html (static notices only)
  static/       CSS and browser assets (future)
migrations/     schema.sql (additive halfvec, offsets, title-weighted FTS and RLS schema)
scripts/        audit_hotpotqa.py; ingest_hotpotqa.py (capped at 1,000); retrieve.py; evaluate_retrieval.py; measure_db_size.py
eval/           versioned evaluation cases (future)
tests/          automated tests
reports/        sanitized probes and AI usage disclosure
docs/           public technical requirements, roadmap, and architecture
```

Current request path: client -> FastAPI app -> health router -> JSON response. The
health route checks process liveness only. The Render startup check loads one
FastEmbed model and logs aggregate measurements; it is not an HTTP diagnostics
route. Gemini and read-only database probes remain explicit commands. A local
ingestion CLI embeds the first 1,000 unique corpus paragraphs and writes them to
Supabase through psycopg. Local retrieval CLIs provide pgvector, FTS, and
Weighted RRF search with source provenance; no HTTP retrieval route was added.
The Phase 1E schema keeps canonical text in `documents.full_text`; chunks store
Unicode character offsets and `halfvec(384)` values. Retrieval reconstructs
the original chunk excerpt from the canonical text. `document_sources` retains
all aliases and evidence sentences. A per-chunk English `tsv` gives title
aliases weight A and body text weight B; source-title and document-text changes
refresh those vectors. GIN indexes FTS and HNSW on `halfvec_cosine_ops` is built
by the bounded ingestion CLI only after the 1,000-row load.

All EvidenceAI DB connections validate the Supabase project reference against
`csenhlrsttuukzwglttf` before connecting. The three tables use RLS; `PUBLIC`,
`anon`, and `authenticated` have no table grants. Direct database credentials
remain backend-only. The previous Mindo project is not used by the app. Live
measurements and limitations are in `reports/phase_1e_optimized.md`.

Gemini answer generation and citation entailment checks remain unimplemented.
Exact text matching confirms that a sentence appears in a source; it does not
prove that the source entails a generated claim.
