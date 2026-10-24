# Phase 3 — Investigation and latency evidence

Date: 2026-10-24

## Scope and deployment gate

The local CLI now performs hybrid retrieval and bounded Gemini investigations.
No records were ingested, no database writes or schema changes were made, and no
API/UI endpoint or deployment was added.

The live read connection was fail-closed and resolved to Evidence_AI project
`csenhlrsttuukzwglttf`. The Supabase region is stated by the project owner as
`ap-southeast-2` (Sydney); this run measured from the developer workstation.
It does not measure Render-to-Supabase latency.

The actual Render service could not be identified from this workspace: there is
no service URL/ID or Render credential/connector available. The deployed service
region, its live `DATABASE_URL`, and its actual Build & Deploy settings therefore
remain unverified. The repository's `render.yaml` requests
`python scripts/download_model.py`; that script downloads into the project-local
`.model_cache` and then verifies an offline load, while runtime
`app/model_cache.py` uses the same directory and `local_files_only=True`. These
repository settings are not proof of the deployed service settings. No
database-backed deployment was attempted.

Before any such deployment, inspect the live Render service region, verify the
redacted `DATABASE_URL` project identity equals `csenhlrsttuukzwglttf`, compare
its live build command with `render.yaml`, and check build logs for
`fastembed_build_cache` with `offline_load_passed: true`. Do not copy the DSN
into logs or this report.

## Implementation

- `GeminiClient` uses the existing `httpx` dependency, defaults to
  `gemini-3.5-flash-lite`, accepts a configured model, keeps the API key in a
  request header, and records each request latency, HTTP status, and numeric
  token counts. A retry is limited to one transient retry and counts against
  the five-request investigation budget.
- One psycopg connection and one reusable HTTP client serve the full
  investigation. `search_evidence` uses the existing BGE semantic retrieval,
  English FTS keyword retrieval, and Python weighted RRF. `get_document` only
  reads a document already surfaced by search. Each tool records embedding,
  SQL/fetch, fusion, and total wall time.
- The loop permits at most four tool calls and five actual Gemini HTTP
  requests, including retries. The final answer is built from verified claim
  text; unverified claims are dropped, and a missing/invalid central claim
  yields `insufficient`.
- Citation validation first checks that each `chunk_id` is among retrieved
  chunks. It then slices canonical `documents.full_text` using retrieved
  `start_char`/`end_char`, checks that the reconstructed text matches the SQL
  result, and searches for the quote with whitespace collapsed only. Trusted
  title aliases and provenance are attached from retrieval results. Source
  metadata supplied by the model is rejected. Quote presence does not prove
  entailment or causality.
- Gemini reports contradiction groups in its final structured output. Python
  retains a group only when every member claim passed citation validation. The
  contradiction test uses a JSON fixture only; no conflicting records were
  added to Supabase. This does not provide a general natural-language
  contradiction/entailment classifier.

## Actual measurements

### Read-only retrieval baseline before the agent

The connection target was checked before connecting. One workstation connection
took **2.4963 s**. A separate `SELECT 1` round trip took **0.8106 s**. On one
natural-language query, three warm samples had median query-embedding time
**0.0400 s**, semantic SQL+fetch **0.9370 s**, keyword SQL+fetch **0.4194 s**,
and RRF **0.000366 s**. These are workstation measurements, not Render metrics.

### Real investigations

| Outcome | DB connect | BGE model load | Tool retrieval | Gemini requests / summed latency | Total | Verified citations |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Insufficient evidence | 3.553413 s | 0.357385 s | 4 search tools, 6.445809 s total | 5 / 5.056361 s | 15.711740 s | 0 |
| Answered | 8.371481 s | 0.351682 s | 1 search tool, 4.240997 s | 3 / 3.855385 s | 17.094912 s | 1 |

The successful investigation's tool call was:

- `search_evidence(query="Ironclad Board established year", k=5)` returned five
  chunks, including `Ironclad Board`, `CSS Virginia`, `USS Monitor`,
  `Ironclad warship`, and `Central battery ship`.
- Search tool wall time was **4.240997 s**: embedding **0.018667 s**, semantic
  SQL+fetch **2.580566 s**, keyword SQL+fetch **1.641381 s**, RRF **0.000113 s**.
- The answer was “The Ironclad Board was established in 1861.” One claim passed
  validation with chunk
  `fede37a5bca9624209d9c0a0d09cd6bd68023b0c7cf58469ad12e6343b2fb227`, exact
  quote “The Ironclad Board was an advisory board established by the Union in
  1861”, and provenance title `Ironclad Board`.
- `get_document` was implemented but was not needed in this investigation.
- A separate read-only `get_document` integration check for that already
  retrieved document returned 533 characters and one source in **0.889220 s**
  SQL+fetch time. This check was outside the investigation and used no Gemini
  request.

The insufficient-evidence run used the first committed dev question. It made
four `search_evidence` calls, returned no claim accepted by citation validation,
and abstained. That run happened before tool arguments/result IDs were included
in the trace, so its individual search strings and result IDs were not retained;
the total call count and per-call timing were retained. No retrieval-quality
metric is inferred from that single question.

Observed per-call SQL+fetch wall times varied substantially between runs. The
successful call took 2.58 s semantic and 1.64 s keyword, compared with baseline
medians 0.94 s and 0.42 s. Connection establishment also ranged from 2.50 s to
8.37 s. The measurements show high and variable workstation-to-database
latency, but cannot isolate network distance from database service load, TLS,
query execution, or workstation conditions. Render's region is unknown, so no
infrastructure change is proposed from this evidence.

### Gemini usage

- Availability smoke: `gemini-3.5-flash-lite` appeared in the API model list and
  a minimal generation succeeded. The model-list probe plus one generation
  request took **1.04 s combined** and reported 7 prompt, 1 candidate, and 8
  total tokens. The model-list page count was not retained, and the combined
  time does not isolate generation latency.
- Insufficient investigation: five successful HTTP 200 generation requests,
  no retries; per-request latencies were **1.102314, 0.840675, 0.848651,
  0.921368, 1.343353 s**. Usage metadata reported 42,038 prompt tokens,
  12,207 cached-content tokens, 116 candidate tokens, and 42,154 total tokens.
- Answered investigation: three successful HTTP 200 generation requests, no
  retries; latencies were **1.280726, 1.326732, 1.247927 s**. Usage metadata
  reported 4,232 prompt, 264 candidate, and 4,496 total tokens.
- Across those checks: nine generation requests; model-list request count was
  not retained.
  The five-request cap applies independently to each investigation.

## Verification

Commands:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -X utf8 scripts/investigate.py "What year was the Ironclad Board established?"
```

The investigation command is read-only. Its JSON trace reports the database
project reference, connection and model-load times, each tool's SQL/fetch
breakdown, each actual Gemini request and its token metadata, citations, and
total duration.

Full test result after implementation: **105 passed**. Tests include request
limits/retries, schema-shaped output, offset reconstruction with Unicode and
repeated text, whitespace-only quote normalization, fabricated chunk/source
rejection, multi-chunk citations, insufficient-evidence behavior, and
fixture-only contradiction handling.

## Limitations and next gate

- Measurements are from the developer workstation. The live Render region,
  deployed build configuration, and deployed `DATABASE_URL` still need
  verification in the Render dashboard before a database-backed deployment.
- The successful and insufficient examples show one supported answer and one
  abstention, not retrieval or answer-quality metrics.
- Quote validation is deterministic evidence-presence checking. It does not
  prove semantic entailment, causality, or that a model-reported contradiction
  is logically correct. Conflict groups are only tested with local fixtures.
- No retrieval-score abstention threshold was calibrated. No synthetic
  conflicting records, additional corpus data, schema changes, UI, or Render
  deployment were introduced.
