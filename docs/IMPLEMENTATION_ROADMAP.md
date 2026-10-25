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

## Current verified milestone state

- Phase 5 staged ingestion reached 50,000 documents on the Frankfurt project;
  consult `reports/capacity_50k.md` for measured counts, storage, and checks.
- Phase 6A retrieval tuning is complete using only the 200-question development
  set; the 40 final candidates remain held out. See
  `reports/retrieval_tuning_50k.md`.
- The existing bounded Gemini investigation agent and citation validator are
  reused by the Phase 4A web application. Semantic retrieval is the public
  default; keyword and hybrid remain selectable.
- Phase 4A local application code and HTTP tests are implemented in this
  milestone. Public Render deployment, actual Gemini quota inspection, and
  request-time Render memory checks remain pending. The zero daily budget keeps
  the endpoint disabled until an operator configures a quota-based limit.
- Document upload/CRUD and held-out final answer evaluation remain separate
  milestones; this web milestone does not modify the corpus or evaluation data.
