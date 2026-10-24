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

## Validation and limitations

- Latest full validation: isolated `.venv`, `python -m pytest -q` - 43 passed.
- Uvicorn started locally and `GET /health` returned `{"status":"ok"}`.
- API, database, retrieval, LLM, reasoning, and evaluation modules remain placeholders
  where their implementation milestones have not started; local corpus preparation
  does not claim database ingestion or RAG behavior.
- Live Gemini generation succeeded with `gemini-3.5-flash-lite`.
- PostgreSQL connection succeeded after a configuration correction; pgvector 0.8.0
  was enabled and a cosine smoke query passed. Baseline database size: 20,491,411
  bytes. Full dataset capacity remains unverified. See reports/database_probe.json.
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
- No database ingestion, retrieval, ranking, citation validation, agentic loop, or
  evaluation-quality metrics are implemented or claimed.
- Independent non-AI implementation contributions are not recorded at this stage.

Local planning and personal preparation notes are excluded from the repository.
- Completed the requested Phase 0 repository tree with project-only root
  instructions and sanitized public requirements/roadmap summaries. Original
  assessment and personal preparation notes remain Git-ignored locally.
