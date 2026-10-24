# AI usage report

Tool: OpenAI Codex. AI assistance is disclosed as a project deliverable.

## Implemented with AI assistance

- Python scaffolding and environment configuration.
- Readiness inventory and Gemini/PostgreSQL diagnostic probes.
- Tests for configuration precedence, ignored paths, HTTP errors, response
  validation, database failures, and secret-safe diagnostic output.
- Setup documentation and technical evidence reports.
- FastAPI app entry point, `/health` router, one API test, and placeholder
  packages for future project components.
- Full package/file skeleton, project-only AGENTS.md, public requirements and
  roadmap summaries, static UI notices, and non-operative script/schema placeholders.
- Render Python Blueprint and startup-only FastEmbed check, including safe timing/RSS
  logging, 384-dimension validation, and tests for secret/vector-free public responses.
- A pinned, streaming HotpotQA audit utility, exact title+paragraph uniqueness
  counts, supporting-sentence coverage checks, unit tests, and aggregate documentation.
- Build-time FastEmbed model download with an offline reload check, an
  offline-only runtime cache loader, and a readiness gate computed from the
  recorded Render measurements.
- Fixed-seed HotpotQA train selection, content-hash deduplication, source-title
  collision preservation, and title-plus-sentence coverage tests.
- Phase 1C additive Supabase schema, paragraph chunking, stable source/chunk IDs,
  local BGE embeddings, parameterized psycopg ingestion, and live size, cosine,
  fresh-connection, and idempotence checks for the capped 100-document slice.
- Phase 1D configurable ingestion limit with a hard 1,000-document ceiling,
  read-only database/table/index/vector-size measurement, and live 100-to-1,000
  Supabase capacity verification, cosine latency benchmark, and idempotence check.
- Phase 2 semantic retrieval, OR-based PostgreSQL FTS, a shared local search
  interface, deterministic Weighted RRF, and an evidence-gated evaluator with
  per-question output. Real before/after Supabase measurements cover the same
  82 dev questions fully represented in the indexed 1,000-document subset.
- Phase 1E project-identity fail-closed checks, additive optimized schema,
  Unicode-safe chunk offsets, halfvec ingestion, title-weighted FTS triggers,
  post-load HNSW creation, security grants/RLS, live 1K ingestion and
  idempotence verification, storage measurements, retrieval evaluation, and
  HNSW-vs-exhaustive ranking comparison on the dedicated Evidence_AI project.
  Mindo was not modified.

## Validation and limitations

- Latest full validation: isolated `.venv`, `python -m pytest -q` - 84 passed.
- Uvicorn started locally and `GET /health` returned `{"status":"ok"}`.
- The previous OR-search baseline lowered equal-weight hybrid metrics on the
  former Mindo-backed subset. Phase 1E moved the same 1,000 corpus documents to
  the dedicated Evidence_AI project; title-weighted OR FTS improved keyword and
  equal-weight hybrid metrics on the same 82 eligible questions. File-upload parsers,
  ingestion beyond 1,000, Gemini RAG, citation
  validation, and final answer-quality evaluation remain incomplete and are not claimed.
- Live Gemini generation succeeded with `gemini-3.5-flash-lite`.
- The old Mindo database probe remains historical. The current Evidence_AI
  target is project `csenhlrsttuukzwglttf`, uses PostgreSQL 17.11 and pgvector
  0.8.2, and measured 18,454,195 bytes after the 1K load. The 10K/50K figures
  remain estimates; see `reports/phase_1e_optimized.md`.
- The owner supplied a Render startup log showing the 384-dimensional FastEmbed
  check passed, with 0.1003s embedding latency and 300,912,640 bytes peak process
  RSS. Local build-time cache and two local restart checks passed; a post-change
  Render deployment/restart check remains pending. Details are in
  reports/render_preflight.md.
- The local corpus audit selected 200 retrieval questions and 40 separate
  candidates with seed 42, produced 50,000 unique content hashes, and verified
  578/578 selected supporting title/sentence references. The retrieval dev set
  and aggregate report are committed; `data/corpus.jsonl` is locally generated
  and Git-ignored. See reports/corpus_audit.json.
- The current build script passed its offline cache reload check at 384
  dimensions. A local FastAPI lifespan startup with the embedding check enabled
  returned HTTP 200 from `/health`; post-change Render build and restart checks
  remain pending. See reports/render_preflight.md.
- A complete streaming scan of HotpotQA `distractor` revision
  `1908d6afbbead072334abe2965f91bd2709910ab` counted 482,021 unique train
  records and 507,494 unique records across train+validation contexts. Validation
  train-only evidence coverage was 73.3% of support sentences and 57.36% of
  questions with all evidence present. One source reference is unresolved.
  Full details and limitations are in reports/hotpotqa_audit.json.
- No ingestion beyond 1,000 documents was performed. Phase 2 retrieval metrics
  remain title-level only; they do not measure answer correctness or entailment.
- The ingestion report records the actual first-run database size change and a
  later size increase observed across a zero-insert rerun; the cause of that
  increase was not established. See reports/ingestion_100.md.
- Independent non-AI implementation contributions are not recorded at this stage.

Local planning and personal preparation notes are excluded from the repository.
- Completed the requested Phase 0 repository tree with project-only root
  instructions and sanitized public requirements/roadmap summaries. Original
  assessment and personal preparation notes remain Git-ignored locally.

## Phase 3 addition — 2026-10-24

- Codex assistance was used to implement the bounded Gemini investigation CLI,
  typed request/response structures, read-only search/document tools, latency
  traces, and two-level citation validation. The repository owner directed the
  scope and should review and be able to explain each component independently.
- Tests cover evidence offset reconstruction, exact quote checks, unsupported
  citation rejection, abstention, tool/request limits, retries, and a
  fixture-only contradiction case. No synthetic conflicting documents were
  inserted into the database.
- Actual local checks used the configured `gemini-3.5-flash-lite` model and the
  fail-closed Evidence_AI Supabase project. One real investigation abstained and
  one returned an answer with one validated citation. Exact request/token and
  timing details are in `reports/phase3_investigation.md`.
- The deployed Render region, environment, and build settings were not
  accessible and are still unverified. No Render deployment was triggered.
