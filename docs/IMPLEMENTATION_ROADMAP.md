# Development roadmap

EvidenceAI was developed in stages so that data quality, storage capacity,
retrieval results, and API usage could be checked before expanding the system.
This is a record of the development sequence, not a list of unfinished work.

## Development stages

1. **Foundation:** FastAPI setup, configuration safety, and service checks.
2. **Ingestion:** HotpotQA audit, chunking, deduplication, embeddings,
   database schema, and staged indexing.
3. **Retrieval:** semantic search, PostgreSQL full-text search, weighted RRF,
   and retrieval evaluation.
4. **Investigation:** Gemini tool calls, multi-step evidence gathering,
   citation checks, contradictions, and insufficient-evidence handling.
5. **Evaluation:** separate development/final datasets, retrieval metrics,
   answer-quality checks, and failure analysis.
6. **Web app:** investigation interface and authenticated document management.
7. **Deployment:** Render hosting, Frankfurt Supabase database, and
   operational checks.

## Project status

- The recorded ingestion run reached **50,000 documents**, 50,018 source
  records, and 50,000 chunks. See the
  [capacity report](../reports/capacity_50k.md).
- Semantic, Keyword, and Hybrid retrieval are implemented. Semantic remains
  the default because it performed best in the recorded comparison.
- The investigation API and document library support questions and
  authenticated upload, replacement, and deletion. Later live checks are
  summarized in [requirements coverage](../reports/final_submission_checklist.md).
- The **45-case final evaluation is complete**: 38 cases used the live
  investigation path, and seven used isolated conflict fixtures.
  See the [Evaluation Report](../EVALUATION_REPORT.md).
- The [public demo](https://evidence-ai-frankfurt.onrender.com/) is hosted on
  Render. The exact deployed revision and memory usage under repeated or
  concurrent requests have not been independently verified.

For setup and known limitations, start with the
[README](../README.md). Earlier phase reports record the state at the time
of each experiment.
