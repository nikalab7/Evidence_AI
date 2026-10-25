# AI Usage Report

## Tools used

- **OpenAI Codex:** assisted with architecture scaffolding, Python
  implementation, tests, local diagnostics, evaluation runners, engineering
  reports, and this submission packaging.
- **Google Gemini (gemini-3.5-flash-lite):** used by the implemented
  investigation engine and the explicitly approved live smoke/evaluation runs.
  Gemini was not the coding assistant in this repository.

The detailed phase-by-phase record is preserved in
[reports/AI_USAGE_REPORT.md](reports/AI_USAGE_REPORT.md).

## Work that received AI assistance

Codex assistance covered project setup and configuration; corpus audit and
reproducible HotpotQA selection; PostgreSQL/pgvector schema and ingestion
utilities; semantic, keyword, and hybrid retrieval; Weighted RRF; the bounded
Gemini tool loop; exact-quote citation and conflict handling; FastAPI pages and
document management; automated tests; evaluation tools; deployment/readiness
checks; technical documentation; and the final packaging documents.

This disclosure does not imply that the owner independently hand-wrote those
changes. Contributions not evidenced in the repository history are not
attributed.

## Developer direction and responsibility

The developer set the assignment as the source of truth, approved the
implementation roadmap, chose major scope and safety boundaries, specified the
Frankfurt migration and staged corpus-ingestion gates, approved live API usage,
and selected the evaluation plan. The developer must be able to explain and
defend the submitted code, reproduce its checks, and make changes without an AI
assistant during the interview.

## Verification and operator-supplied evidence

Local automated tests, scripts, and development experiments are identified in
their corresponding reports. The 50,000-document ingestion and database
measurements are recorded in [the capacity report](reports/capacity_50k.md).
Gemini evaluation request counts and answer/retrieval metrics are in
[the final evaluation report](EVALUATION_REPORT.md).

The owner supplied the public demo URL and the Cyma Watches / Universal Genève
live answer. The owner also reported applying the managed-upload migration and
completing live CRUD smoke tests. These are labeled owner-reported in project
documentation; they are not represented as independently rechecked during this
packaging work. No Render deployment was triggered here.

## Rejected or bounded AI suggestions

- A broad prompt expansion was measured on development questions and fixtures,
  then rejected because it did not improve aggregate answer-span score and
  increased request count and median latency.
- Hybrid retrieval was not made the default merely to satisfy the assignment.
  Recorded retrieval metrics favored Semantic for the investigation default;
  Keyword and Hybrid remain available.
- Exact quote matching is not described as proof of entailment.
- No public keep-alive endpoint, production schema migration, production
  corpus edit, or automatic deployment was introduced as part of this
  packaging work.

## Known limits

The evaluation set is small; answer-span scoring is a string-match proxy;
conflict detection remains dependent on model-generated conflict groups; the
DHL relationship error demonstrates a multi-hop reasoning limitation; and
current Render deployment state, all-format live upload behavior, and
repeated/concurrent production memory behavior were not independently
revalidated during packaging.
