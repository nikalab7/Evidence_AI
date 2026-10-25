# Phase 7.1 — Live Smoke and Evaluation Plan

Date: 2026-10-25

Target: Frankfurt Evidence_AI (`nldnpqhqrfwjgxcqeuru`)

Status: development smoke completed; final evaluation pending separate approval

## Configuration and quota preflight

- A sanitized configuration check confirmed `GEMINI_API_KEY` and `DATABASE_URL` are configured and the database URL identifies the expected Frankfurt project. Secret values and the connection string were not printed.
- The local `.env` daily budget remained unchanged at 0. The smoke subprocess received `INVESTIGATION_DAILY_BUDGET=1` only for that process.
- The API key successfully made three Gemini requests. Remaining model/project quota could not be queried from this workstation. Google documents that active rate limits vary by model, project, and tier and are viewable in AI Studio; check the target project's current [rate limits](https://ai.google.dev/gemini-api/docs/rate-limits) and [usage/billing](https://ai.google.dev/gemini-api/docs/billing) before final approval.

## Read-only indexed evidence check

The prior broad full-corpus evidence scan was replaced with a scoped query using the indexed normalized source-title field, then matching required normalized sentences and reconstructing only the associated paragraph chunks.

Actual Frankfurt check:

- Project reference: `nldnpqhqrfwjgxcqeuru`.
- Indexed document count: 50,000.
- Answerable final cases eligible: 30/30.
- Required supporting title/sentence references found: 62/62 (100%).
- Selected source/chunk rows read: 55.
- Database access was read-only/autocommit; no writes were issued.

The identity guard remains fail-closed before SQL. The CLI requires all answerable cases and all references to be present.

## One authorized development smoke

An initial attempt in the restricted execution sandbox stopped at database connection establishment and made zero Gemini requests. The authorized retry used a separate ignored result/ledger path and completed the one development question.

| Measurement | Actual result |
| --- | ---: |
| Development question | `dev-smoke-5ae7aadd5542993210983ee5` |
| Gemini model | `gemini-3.5-flash-lite` |
| Retrieval mode | Semantic |
| Search tool calls | 1 |
| Retrieved chunks | 5 |
| Top result | `Anwar Sadat`, rank 1 |
| Gemini HTTP requests | 3 |
| Total investigation latency | 5.260586 seconds |
| Result status | `answered` |
| Draft citations | 2 |
| Verified citations | 1 |
| Rejected citations | 1 |
| Citation validity | 0.5 |
| Sanitized diagnostic | `citation_rejected` |

The generated answer identified Muhammad Anwar el-Sadat as Egypt's third president. The claim was not treated as an accuracy pass: one drafted citation was rejected. This was a development smoke, not a scored final case. Total Gemini requests consumed by the successful smoke: **3**; the failed connection attempt consumed **0**.

The ignored retry result is `reports/final_evaluation_smoke_retry.jsonl`. It contains the case answer and citation details; it is not committed.

## Final evaluation plans

The recommended economical plan uses Semantic generation once for each of the 38 live cases, plus one agent run for each of the 7 conflict fixtures: **45 investigations, maximum 225 Gemini HTTP requests**. A rough planning range is 135–225 calls from prior observations of 3–5 calls per investigation; it is not a prediction. The 3 smoke requests are separate from that estimate.

After all 45 investigations complete, the CLI runs a separate retrieval-only comparison on the same 30 answerable questions using Semantic, Keyword, and Hybrid, with top_k=10, candidate_k=20, and equal-weight RRF k=60. It does not call Gemini. Retrieval metrics will be labeled separately and will not be presented as answer accuracy. Answer quality is reported for Semantic only in this plan.

The original full answer comparison remains available with `--comparison-plan full`: 121 investigations and at most 605 Gemini requests. It generates answers in all three retrieval modes and preserves the same fixture handling.

Offline audits executed both plans and passed. They confirmed 45 cases, 30 answerable cases, 8 unanswerable cases, 7 conflict fixtures, 62/62 local corpus references, and disjoint retrieval development IDs. The default plan reports 45/225; the full plan reports 121/605. No final Gemini investigation or held-out result was run.

Recommended final command, **only after separate operator approval and a fresh quota check**:

```powershell
.\.venv\Scripts\python.exe -m scripts.evaluate_final --live --final --comparison-plan economical --confirm-api-usage
```

Full comparison command:

```powershell
.\.venv\Scripts\python.exe -m scripts.evaluate_final --live --final --comparison-plan full --confirm-api-usage
```

The complete local suite passed **229 tests**. No production database write, schema change, deployment, or held-out Gemini call occurred.
