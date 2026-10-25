# Phase 7 — Final Evaluation Plan and Quality Report

Status: **prepared; final evaluation pending separate operator approval**

No held-out final investigation has run. Metrics for the final set remain pending.

## Dataset and isolation

- The fixed set contains 45 cases: 25 multi-hop/cross-document cases, 5 single-hop cases, 8 unanswerable cases, and 7 fixture-only conflict cases.
- Thirty answerable cases have complete gold evidence; 8 cases are unanswerable. The 7 conflict cases use synthetic evidence injected into the agent and are not indexed in Supabase.
- The separate retrieval development set contains 200 questions. It remains separate from final answer scoring; one development question was used for the authorized smoke only.
- The runner never sends gold answers to Gemini. The retrieval-only stage receives only question text, case IDs, and support references; its input omits gold answers.
- Final evaluation uses the immutable manifest and case file. Do not edit gold answers based on observed model output.

## Indexed coverage preflight

The read-only Frankfurt preflight passed on 2026-10-25:

| Check | Result |
| --- | ---: |
| Project reference | `nldnpqhqrfwjgxcqeuru` |
| Indexed documents | 50,000 |
| Answerable cases with complete indexed support | 30 / 30 |
| Exact title/sentence references found | 62 / 62 |
| Selected provenance/chunk rows read | 55 |

Coverage reads are scoped to the required normalized source titles and sentences, then reconstructs paragraph text only for matching document IDs. It does not scan all corpus rows. No database write or schema change was performed. The final command repeats this identity, count, and complete-evidence gate before any Gemini investigation.

## Authorized development smoke

One development smoke completed with the production investigation pipeline. A preceding sandbox-only connection attempt stopped before a Gemini request; the authorized retry succeeded.

| Measurement | Result |
| --- | ---: |
| Gemini HTTP requests | 3 |
| Gemini model | `gemini-3.5-flash-lite` |
| Retrieval mode | Semantic |
| Search tool calls | 1 |
| Retrieved chunks | 5 |
| Top result | `Anwar Sadat` (rank 1) |
| Draft citations | 2 |
| Verified citations | 1 |
| Rejected citations | 1 |
| Total investigation latency | 5.260586 s |
| Predicted status | `answered` |

The response named Muhammad Anwar el-Sadat for the development question. This is not a final accuracy result: one citation was rejected, so the smoke did not pass as a citation-clean answer. The smoke used 3 Gemini requests; the failed earlier connection attempt used 0. No final-set investigation ran.

The current remaining provider quota could not be read from this workstation. Google directs users to the selected project’s AI Studio rate-limit and usage pages; limits vary by model, project, and tier ([Gemini API rate limits](https://ai.google.dev/gemini-api/docs/rate-limits), [usage and billing](https://ai.google.dev/gemini-api/docs/billing)). Check the project and model there immediately before approving the final run.

## Recommended economical evaluation

The default `economical` plan runs each of the 45 distinct cases through the agent once:

- 38 live investigations (30 answerable and 8 unanswerable) in Semantic mode.
- 7 conflict-fixture investigations through the production agent and validators, using isolated synthetic evidence.
- Maximum: 45 investigations × 5 Gemini HTTP requests = **225 requests**.
- Planning range: **135–225 requests**, based on prior observations of 3 and 5 requests per investigation; this is a rough estimate, not a quota guarantee. The Phase 7.1 development smoke used 3 requests, but is not included in the final-set estimate.
- After all agent investigations complete, the runner performs a separate retrieval-only comparison on the same 30 answerable cases in Semantic, Keyword, and Hybrid modes. This step makes database/search calls only and no Gemini calls.
- Retrieval-only settings: top_k=10, candidate_k=20, Semantic weight 1.0, Keyword weight 1.0, RRF k=60. Each mode’s Recall@5, Recall@10, MRR, median latency, and p95 latency is reported separately from answer quality.
- Answer correctness, abstention, conflict, and citation metrics in this plan are reported for Semantic generation only. Keyword/Hybrid retrieval metrics are not answer-accuracy metrics.

### Full comparison remains available

For reproducibility, the original `full` plan remains selectable: generate answers in Semantic, Keyword, and Hybrid for the 38 live cases, plus seven fixture investigations: **121 investigations**, up to **605 Gemini requests**. It also runs the retrieval-only three-mode comparison after all agent results complete.

## Metrics and interpretation

- Retrieval Recall@5/10 and MRR are support-title metrics for the top-ranked chunks. Retrieval-only scores use a uniform single query per case; they do not measure multi-step answer quality.
- Answer-span match and exact match are string-based proxies against the verified central claim, not human factual judgments.
- Answer correctness is scored for answerable and unanswerable cases. Correct abstentions are counted separately from correct answers.
- Abstention precision/recall uses the 8 unanswerable cases. Conflict detection uses the 7 isolated fixtures.
- Citation validity is verified citations divided by drafted citations. Exact quote presence does not prove claim entailment.
- The per-case JSONL records status, answer, citations, evidence coverage, ranks, tool/API counts, latency, and sanitized error labels. It is Git-ignored and checkpointed so completed investigations are not repeated.

## Commands

Audit plan and immutable local assets without Gemini or database access:

```powershell
.\.venv\Scripts\python.exe -m scripts.evaluate_final
.\.venv\Scripts\python.exe -m scripts.evaluate_final --comparison-plan full
```

Repeat the read-only indexed evidence gate:

```powershell
.\.venv\Scripts\python.exe -m scripts.evaluate_final --check-indexed-coverage
```

The one authorized development smoke command used a process-only budget override; it did not edit `.env` or Render:

```powershell
$env:INVESTIGATION_DAILY_BUDGET = "1"
.\.venv\Scripts\python.exe -m scripts.evaluate_final --live --dev-smoke --confirm-api-usage --max-investigations 1
Remove-Item Env:INVESTIGATION_DAILY_BUDGET
```

**Do not run the final commands until the operator separately approves the estimated Gemini usage and confirms quota.** Default economical run:

```powershell
.\.venv\Scripts\python.exe -m scripts.evaluate_final --live --final --comparison-plan economical --confirm-api-usage
```

Original full comparison:

```powershell
.\.venv\Scripts\python.exe -m scripts.evaluate_final --live --final --comparison-plan full --confirm-api-usage
```

`INVESTIGATION_DAILY_BUDGET` must be set to a positive local value for either live run. It remains process-local to the evaluation CLI; it does not change Render’s setting and is not a durable global quota. Gemini quota availability is not checked automatically.

## Pending results and safeguards

- Final retrieval and answer metrics: **pending**; no held-out case has been sent to Gemini.
- Final quality, conflicts, failure analysis, and full-run latency: **pending**.
- `pytest -q`: 229 passed in this Phase 7.1 checkout.
- No production writes, schema changes, deployment, Mindo/Sydney access, or held-out-set tuning were performed.
- The 45-case result file, retrieval comparison JSON, and budget ledger are Git-ignored. The runner uses a lock, fsync checkpoints, and does not automatically retry an investigation with a reservation but no saved result.
