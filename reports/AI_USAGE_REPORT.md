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

- Latest full validation: isolated `.venv`, `python -m pytest -q` - 112 passed
  after the Phase 5 staged 50,000-document ingestion.
- Uvicorn started locally and `GET /health` returned `{"status":"ok"}`.
- The previous OR-search baseline lowered equal-weight hybrid metrics on the
  former Mindo-backed subset. Phase 1E moved the same 1,000 corpus documents to
  the dedicated Evidence_AI project; title-weighted OR FTS improved keyword and
  equal-weight hybrid metrics on the same 82 eligible questions. Later Phase 3
  implemented Gemini investigation and citation validation; Phase 5 loaded
  50,000 documents. File-upload parser coverage and final answer-quality
  evaluation remain incomplete and are not claimed.
- Live Gemini generation succeeded with `gemini-3.5-flash-lite`.
- The old Mindo database probe remains historical. The former Sydney
  Evidence_AI project is `csenhlrsttuukzwglttf`; the current Frankfurt target
  is `nldnpqhqrfwjgxcqeuru`, PostgreSQL 17.11 with pgvector 0.8.2. The measured
  Frankfurt database size after the 1K load is 18,478,771 bytes. Storage
  projections remain estimates; see `reports/region_migration.md` and the
  historical snapshot `reports/phase_1e_optimized.md`.
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
- At the Phase 1E checkpoint, ingestion was capped at 1,000 documents; Phase 5
  later loaded 50,000. Retrieval metrics remain title-level and do not measure
  answer correctness or entailment.
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

## Region migration addition — 2026-10-25

- Codex assistance was used to update the fail-closed Frankfurt project
  reference, prepare a distinct non-deployed Render Frankfurt Blueprint, and
  run the approved 1,000-document migration and read-only verification. The
  project owner supplied the Frankfurt endpoint and updated the local
  credential. Mindo and Sydney were not modified.
- Live checks measured Frankfurt connection/`SELECT 1` latency, exact corpus
  and chunk reconstruction, security grants, retrieval, and Gemini answer and
  abstention behavior. The full suite passed 106 tests. Actual measurements,
  limitations, and Render follow-up steps are in `reports/region_migration.md`.

## Phase 5 addition — 2026-10-25

- Codex assistance was used to implement the staged, resumable ingestion CLI,
  focused stage-safety tests, and the audit report; to monitor detached local
  runs; and to execute the approved checks against the Frankfurt Evidence_AI
  project. The owner approved the 50K target and capacity thresholds.
- The run used the existing schema, paragraph chunking, BAAI/bge-small-en-v1.5,
  and four local embedding threads. It did not write to Mindo or Sydney, change
  schema/retrieval/Gemini/UI code, or execute destructive SQL.
- Live verification reached 50,000 documents, 50,018 provenance records, and
  50,000 chunks; integrity and idempotence checks passed. The final measured DB
  size was 304,576,179 bytes, below the 450 MB gate. The complete suite passed
  112 tests.
- Full development retrieval results on 200 eligible questions and the matched
  82-question regression comparison are recorded in `reports/capacity_50k.md`.
  All three retrieval modes regressed on the matched 1K cohort, especially OR
  keyword search. The 40 final candidates were checked for evidence coverage
  only and were not used to tune retrieval or invoke the investigation agent.
- A 221,184-byte difference between the final stage-size sample and the
  zero-insert rerun remains unexplained. Supabase physical disk usage was not
  measured through the dashboard; the report labels the WAL/headroom result as
  an SQL-based estimate.

## Phase 6A addition - 2026-10-25

- Codex assistance was used to diagnose PostgreSQL full-text retrieval latency, implement a backward-compatible informative-term keyword strategy, and build a repeatable development-set tuning runner. The project owner specified the candidate approaches, dataset boundary, and evaluation requirements.
- SQL diagnosis, threshold selection, and the eight-configuration RRF comparison used only the 200-question `eval/retrieval_dev.jsonl` development set. The held-out candidate file was not opened or used. Database benchmarking was read-only against Frankfurt; no schema or index changes were made.
- The measured 0.05 informative-term cutoff improved keyword Recall@10 to 0.455 on the development set. Semantic-only remained the recommended default based on higher Recall@10/MRR and lower latency than positive-keyword hybrid variants. Results and limitations are in `reports/retrieval_tuning_50k.md`.

## Phase 4A web application addition - 2026-10-25

- Codex assistance was used to connect the existing bounded Gemini investigation
  agent, semantic-default retrieval, and citation validator to a FastAPI JSON
  endpoint and same-service responsive page. The owner specified scope,
  retrieval default, safety restrictions, and deployment gates.
- Added strict question/body validation, configurable token and timeout bounds,
  atomic process-local per-IP/daily/concurrency limits, startup and sampled
  request RSS logging, and sanitized HTTP errors. No dependency, schema, corpus,
  Gemini-agent step budget, or evaluation dataset was changed.
- API tests exercise a successful exact-quote citation and an insufficient-
  evidence result over the HTTP route using scripted Gemini responses and a
  fake database connection. These tests verify local application behavior but
  are not live Gemini or Supabase verification.
- The Gemini quota dashboard and Render service were not accessible from the
  workspace. The daily budget remains zero (API disabled) until the owner
  checks quota and configures a safe cap. Request-time Render RSS, public URL,
  cold start, and two-live-request checks remain pending; see
  `reports/phase4a_web_app.md`.

## Phase 4A.1 production validation addition — 2026-10-25

- Codex assistance was used to fix conflict-group serialization from the typed
  investigation result through the public API, avoid repeating claim text in
  the page while retaining citations, and harden per-IP limiting by ignoring
  caller-controlled `X-Forwarded-For`, validating Cloudflare's single client-IP
  header, and disabling Uvicorn proxy-header rewriting.
- Added local regression tests and `reports/phase4a_1_production_validation.md`
  with the owner-run live verification sequence. The full local suite passed
  151 tests.
- No Render deployment, public API request, Gemini call, or database query was
  made: authenticated Render deployment/log access was not available. The
  reported one-request production baseline and configured budget are owner-
  supplied, not independently verified. Three sequential and two concurrent
  request memory measurements remain pending.
- After the owner supplied a successful two-source Cyma Watches / Universal
  Genève investigation response, Codex assistance was used to add the exact
  evidence chain to the README and an interview walk-through. No Render log
  access was available; the matching `investigation_memory` event remains
  pending and no timing or memory values were inferred for that request.

## Phase 6B document management addition - 2026-10-25

- Codex assistance was used to implement bounded PDF/DOCX/TXT/Markdown parsing,
  two offset-preserving chunk strategies, admin-authenticated upload/list/
  inspect/replace/delete endpoints, a minimal Document Library, and isolated
  tests. The owner specified the document-management scope and production-data
  safety boundary.
- The proposed `managed_uploads` migration is additive and was not applied.
  No Supabase connection, production read/write, Render deployment, or change to
  the 50,000 indexed records was made. Neither held-out evaluation file was
  opened. CRUD transaction behavior was verified with isolated fake resources;
  the complete local test suite passed 181 tests.
- The BGE chunking comparison ran locally against a small synthetic fixture
  using the existing cached model. Both strategies covered and ranked all three
  fixture evidence sentences; this is not a corpus retrieval-quality result.
  Details and single-run timings are in `reports/document_ingestion.md`.
- The complete test result and any remaining operational limitations are in
  `reports/document_ingestion.md`; database grants/trigger behavior and Render
  memory remain unverified pending explicit migration and deployment approval.

## Phase 6B.1 pre-deployment safety review — 2026-10-25

- Codex assistance was used to review Phase 5 schema guards and the proposed
  managed-upload migration, add a strict allowlist for the approved additional
  table, and include the empty managed table in capacity measurements. The
  Frankfurt project identity guard and corpus integrity checks were preserved.
- The proposal now pairs `source_id` and `doc_id` with a composite foreign key,
  checks migration reapplication against the expected schema/security contract,
  and uses a monotonic row version for stale replacement detection. Uploads
  split oversized paragraphs, cap chunk count, coalesce bounded ASGI body
  fragments, and serialize write requests per process to bound
  multipart/embedding concurrency.
- Added regression tests for schema allowlisting, manager-table constraints,
  stale replacements after a version change or delete, long Unicode paragraphs,
  upload concurrency, fragmented bodies, and capacity projections. The full
  local suite passed 192 tests.
- No Supabase connection, SQL migration, Render setting, or deployment action
  was performed. No PostgreSQL server was available for integration testing;
  the migration, database transaction behavior, grants, and live upload memory
  remain unverified. See `reports/phase6b_1_safety_review.md` for the operator
  checklist and pending gates.

## Phase 6B.2 activation preflight — 2026-10-25

- Codex assistance was used to run a sanitized local tool/configuration check,
  verify the local test suite, and document the activation gate results and
  operator handoff in `reports/phase6b_2_activation.md`.
- Docker/Podman and a local PostgreSQL service were unavailable, so real
  PostgreSQL integration could not start. No production connection, migration,
  CRUD operation, Render setting change, or deployment was attempted. The
  conditional activation remains blocked pending a disposable local database.
- The full local test suite passed 192 tests; this is not PostgreSQL or
  production verification.

## Phase 6B final activation attempt — 2026-10-25

- Codex assistance was used to statically review the complete proposed
  migration, inspect the available tool catalog, update the activation report
  and README, and rerun the local test suite.
- No Supabase database connector was available in this session. The migration
  was not applied, and no production database or Render setting was accessed.
  The owner-provided Frankfurt counts were not independently verified. The
  activation is blocked until a connected Supabase tool is available to run
  the required preflight.
- The full local suite passed 192 tests; this is not live PostgreSQL or
  production verification.

## Phase 6B final Render handoff — 2026-10-25

- Codex assistance was used to record the operator-reported migration result,
  review the existing document-management routes and authentication gate, and
  change the Frankfurt Blueprint's daily investigation budget from a hardcoded
  zero to a manually managed `sync: false` value. A regression test protects
  the Blueprint setting and deployment commands.
- The connected Supabase and Render tools were unavailable. Operator-reported
  production database checks are labeled as such; they were not independently
  queried. No production records or live Render settings were changed, and no
  deployment or live CRUD test was performed.
- The complete local suite passed 194 tests. This does not verify production
  migration state, Render secrets, or upload memory.

## Managed-document semantic replacement diagnosis - 2026-10-25

- Codex assistance was used to inspect semantic ranking, Gemini tool-query
  rewriting, HNSW behavior, filters, upload replacement, and exact-quote
  validation. A bounded exact-title semantic rescue now uses the original
  question when needed; safe operational diagnostics distinguish retrieval
  misses, abstentions, missing/rejected citations, and verified citations.
- A read-only query confirmed the Frankfurt synthetic replacement metadata and
  three chunks. One real Gemini tool-planning request and one local full
  investigation were made for the user-provided synthetic question. The local
  run answered with a verified quote. One public Frankfurt API request still
  returned HTTP 200 with `insufficient`; no trace was exposed by that deployed
  version, so the historical Render failure stage is not yet confirmed.
- A read-only before/after comparison used only the 200-question retrieval dev
  set. Recall@5 changed from 0.8425 to 0.8700, Recall@10 from 0.8775 to 0.9050,
  and MRR from 0.928266 to 0.936599. Two individual questions regressed in MRR.
  The 40 held-out candidates were not opened. A fresh broad evidence-coverage
  query timed out without changing data; eligibility used the previously
  recorded all-200-dev evidence gate.
- Automated tests exercise upload/replacement retrieval, exact citations,
  diagnostic categories, private-data-safe logs, and unchanged retrieval when
  title rescue is unnecessary. The full local suite passed 206 tests. The
  corrected code has not been deployed; the operator must deploy the pushed
  commit and inspect its sanitized `investigation_diagnostic` log event.

## Phase 7 evaluation preparation - 2026-10-25

- Codex assistance was used to prepare a deterministic 45-case final answer
  evaluation set, preserving the selected HotpotQA candidate gold answers,
  and to implement a budget-gated, resumable CLI using the production
  investigation agent, retrieval modes, and citation validator. Gold answers
  remain evaluator-side; only question text is passed to the agent.
- The set contains 25 multi-hop/cross-document candidates, 5 single-hop facts
  derived from separate supporting sentences, 8 synthetic unanswerable cases,
  and 7 fixture-only conflict cases. Conflict evidence is injected into the
  agent for reasoning/citation checks and was not written to Supabase.
- The local generated corpus check found all 62/62 supporting references for
  the 30 answerable final cases and confirmed the eight synthetic identifiers
  are absent. The prior capacity report records 40/40 final candidates and
  92/92 support references in the indexed corpus. A fresh read-only production
  coverage query did not return a result in this session, so current live
  coverage is not claimed as independently reverified.
- The full local test suite passed 224 tests. The final live CLI now performs a
  read-only fail-closed preflight for the Frankfurt project, the expected
  50,000 indexed documents, and complete support coverage before it can make
  any final-evaluation Gemini calls. A one-question dev smoke was
  attempted through the runner but stopped before model initialization,
  database connection, or Gemini usage because the local investigation daily
  budget is 0. No final held-out Gemini calls were made. Full evaluation usage
  is estimated at 121 investigations and at most 605 Gemini HTTP requests;
  Render's `sync: false` budget and provider quota were not accessible.
- No database writes, schema changes, deployment, corpus changes, or held-out
  tuning were performed. Detailed scope and reproducible commands are in
  `reports/final_evaluation.md`.

## Phase 7.1 smoke and economical final-evaluation plan — 2026-10-25

- Codex assistance was used to narrow the read-only indexed-coverage query to
  the 62 required title/sentence references, add the default economical
  45-investigation plan, preserve the complete 121-investigation plan, and add
  a separate no-Gemini retrieval comparison across Semantic, Keyword, and
  Hybrid for the same 30 answerable cases. Retrieval-only scores are kept
  separate from generated-answer quality; economical answer quality is
  reported for Semantic only.
- The Frankfurt read-only check actually passed: 50,000 indexed documents,
  30/30 answerable cases, 62/62 required evidence references, and 55 selected
  provenance/chunk rows read. The exact project identity was checked before
  the SQL query. No database data or schema was modified.
- One authorized development smoke completed with one Semantic search tool
  call and 3 Gemini HTTP requests in 5.260586 seconds. It returned an answer
  with `Anwar Sadat` ranked first; one of two draft citations verified and one
  was rejected. The smoke was therefore recorded as a mixed citation result,
  not an accuracy pass. A preceding sandbox connection failure made 0 Gemini
  calls. The available provider quota could not be inspected from this
  workstation; the owner must check the selected project in AI Studio.
- Offline plan audits passed for economical (45 investigations, maximum 225
  Gemini requests) and full (121 investigations, maximum 605 requests). The
  45-case held-out evaluation has not been run. No production write, schema
  change, deployment, Mindo/Sydney access, or held-out Gemini request occurred.
- The complete local suite passed 229 tests. See
  `reports/phase7_1_live_smoke.md` and `reports/final_evaluation.md` for
  measurements and reproduction commands.
