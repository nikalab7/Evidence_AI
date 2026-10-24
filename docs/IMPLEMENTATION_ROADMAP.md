# Implementation roadmap

Work in small tested milestones. Do not load the full dataset until uniqueness,
evaluation evidence coverage, model availability, database capacity, and actual
deployment memory have been checked.

1. **Foundation:** configuration safety, FastAPI health endpoint, project
   packages, and environment/service diagnostics.
2. **Ingestion:** dataset and evaluation audit, parsers, deduplication, two
   chunkers, embeddings, database schema, and staged ingestion.
3. **Retrieval:** keyword and semantic search, filters, ranking, and separate
   retrieval evaluation.
4. **Investigation:** Gemini client, structured tools, bounded multistep RAG,
   citation checks, conflicts, and abstention.
5. **Evaluation:** reproducible test set, metrics, configuration comparison,
   and failure analysis.
6. **Backend and interface:** document API, investigation API, and source views.
7. **Deployment and handoff:** public hosting, persistence checks, setup guide,
   evaluation report, and AI usage report.

The current repository implements the foundation, service probes, a read-only
HotpotQA corpus/evidence audit, and the verified 100-document Phase 1C slice.
That slice creates an additive documents/provenance/chunks schema, stores
384-dimensional embeddings, and verifies idempotence and cosine-distance SQL
search. The next ingestion scale (1,000 documents) has not started. Remaining
Phase 1 work includes other file parsers, the second chunking strategy and its
comparison, and staged capacity measurements. Retrieval, investigation,
answer evaluation, and user-facing document routes remain incomplete.
