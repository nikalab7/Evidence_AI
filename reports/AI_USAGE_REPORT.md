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
  increase was not established. See reports/archive/ingestion_100.md.
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
  timing details are in `reports/archive/phase3_investigation.md`.
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
  `reports/archive/phase7_1_live_smoke.md` and `reports/final_evaluation.md` for
  measurements and reproduction commands.

## Phase 7.3 final evaluation - 2026-10-25

- Codex assistance was used to resume the existing final-evaluation checkpoint,
  implement stop-on-provider-quota behavior for evaluation calls, and correct
  final report aggregation for answer-span denominators, conflict fixtures, and
  total Gemini request counts. The existing nine final investigations were not
  rerun.
- The authorized batch completed 36 additional investigations using 131 Gemini
  HTTP requests. All 45 final cases now have results; 162 requests were recorded
  across the full run. No 429, provider quota error, or investigation error was
  returned. The operator supplied Tier 1 quota values; the runner did not query
  the provider quota endpoint.
- The retrieval-only comparison used the same 30 answerable final questions for
  Semantic, Keyword, and Hybrid and made no Gemini generation requests. No
  ranking or prompt tuning was performed against these held-out cases.
- The final report distinguishes retrieval quality from answer correctness and
  exact-quote presence from factual entailment. The complete local suite passed
  236 tests. No production data, schema, Render configuration, or deployment
  was changed. See `reports/final_evaluation.md` for measurements and limits.

## Phase 7.4 targeted quality improvement - 2026-10-25

- Codex assistance was used to audit the frozen final checkpoints, reproduce the
  central-claim conflict rejection, and add private per-citation diagnostics.
  Original rejected quote strings and conflict groups were not saved, so their
  historical contents are explicitly left unknown. The DHL audit found a lost
  business-partner relationship despite complete visible supporting evidence.
- Twenty unchanged development questions and ten independent synthetic fixtures
  were prepared. The operator separately approved 60 live investigations and up
  to 300 Gemini requests. The comparison completed 60 investigations using 228
  requests (109 baseline, 119 prompt candidate), with no quota or runtime errors.
- The expanded prompt candidate improved conflict status scores from 3/5 to 5/5
  but left the dev central-claim span score at 9/20, increased cost, and regressed
  the partner control's central-claim score. The candidate was rejected and saved
  as a reproducible patch; runtime generation prompts were restored.
- The retained deterministic validator fix replayed all 30 saved baseline drafts,
  first reproducing their original outputs, then changing only two unresolved
  conflict statuses. Conflict recognition became 5/5 with no additional API
  requests; the dev score, quotations and negative-control results were unchanged.
  This replay is distinguished from a fresh live run of the retained build.
- The final evaluation dataset, report and checkpoints remained unchanged.
  No production records, schema or deployment were changed. The local rolling
  ledger was preserved and the process-only budget override restored. See
  `reports/phase7_4_quality_improvement.md` for results and limitations.
- The complete local suite passed 267 tests, including identical generation
  messages before/after the retained fix and strict handling of invalid central
  claims, unknown sources, failed quotations and exhausted budgets.

### Phase 7.4 post-hoc final conflict-fixture check - 2026-10-25

- The first explicitly approved attempt ran only the seven final conflict
  fixtures. All seven hit `upstream_network_error` after 14 Gemini HTTP
  attempts; no model output, tool call, or citation was produced. That attempt
  was not retried until the later probe passed and a separate rerun was
  approved. Its local checkpoint is preserved at
  `reports/.phase7_4_final_conflict_results.jsonl`.
- The one-time Gemini service probe passed for `gemini-3.5-flash-lite`: one
  generation call returned text, 8 tokens were reported, and elapsed time was
  1.173 seconds. The probe is separate from the investigation request counts.
- After the probe, Codex ran the seven final conflict fixtures once more using
  the retained build, the Frankfurt identity guard, and the shared reservation
  ledger. The rerun completed 7/7 expected conflict statuses, made 21 Gemini
  HTTP attempts and 7 tool calls, and passed exact-quote checks for 14/14 draft
  citations. Median/p95 investigation time was 3.122/3.305 seconds. The
  development-selected fix was not changed based on these final fixtures. The
  separate result checkpoint is preserved at
  `reports/.phase7_4_final_conflict_results_network_retry.jsonl`.
- The process-local daily ceiling was set to exactly 120 for the rerun because
  the shared ledger already had 113 recent reservations; `.env` remains at 60
  and Render is unchanged. No database or dataset writes occurred. The full
  local suite passed 267 tests. The frozen-report regression test verifies the
  original report hash after removing only the approved post-hoc comparison
  block.

### UI template update - 2026-10-26

- The supplied newer investigation and library HTML were integrated into the
  served templates while preserving existing routes and DOM contracts. The
  investigation request now sends the captured question before clearing the
  textarea; claim text, verified quotations, source titles/links, and full
  claim/passage IDs remain visible. Citation panels are compact by default,
  with only the first citation expanded. Native select option colors and the
  accent color are set from the existing green/gray palette to avoid the
  browser's default blue selection where the platform honors option styling.
- The question textarea grows up to its configured bound, Enter submits and
  Shift+Enter inserts a line break, reduced-motion preferences are honored, and
  the library login returns to a compact unlocked state while keeping the token
  in page memory only.
- Verification: 267 local pytest tests passed; both inline scripts passed
  Node.js syntax checks. No Gemini requests, database writes, or deployment
  occurred. In-app visual browser verification was unavailable in this runtime.

### Evaluation question tabs - 2026-10-26

- Reworked the picker to match the supplied four-tab design and removed the
  lower instructional and metrics sections. The three runnable groups contain
  three exact evaluation questions each: single-hop, multi-hop, and
  unanswerable; all nine source rows use `execution_mode=live`. The 2 Chainz
  item was replaced with a multi-hop question whose completed evaluation row
  recorded a correct answer and retrieval of both support references. No new
  live request was made, and no gold answers or forced result statuses are shown.
- The Conflicting tab's three fixture prompts now fill the question field when
  selected, but never auto-submit. The note states their synthetic evidence is
  not indexed in production, so a live investigation cannot reproduce the
  fixture test. All twelve examples fill and focus the existing textarea.
- Added a compact `Clear` control that resets the question, retrieval mode,
  displayed answer, citations, status, and errors to the initial page state
  without reloading. It is disabled while an investigation is running. Citation
  quotes use normal body text, and the explanatory citation-verification footer
  was removed.
- Fixed result-page bottom scrolling: the page now reserves space based on the
  actual fixed composer height, updating when the viewport or mobile visual
  viewport changes and when the composer resizes. This prevents the final
  evidence/citation content from ending underneath the question panel.
- The evidence panel continues to show each actual claim statement alongside
  its human-readable evidence heading and technical claim ID. Automated checks
  cover exact question strings, category counts, execution modes, and the
  question-clear behavior and fixture labeling. The full local suite passed
  268 tests. No Gemini calls, production writes, or deployment occurred.
