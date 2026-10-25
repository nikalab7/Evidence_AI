# Phase 7 — Final Evaluation & Quality Report

Evaluation status: **prepared_live_evaluation_pending**

No full live answer evaluation has been run in the current workspace. Cells marked `pending` are intentionally unmeasured.

- Final dataset SHA-256: `d2663d7a8deaf573d8eaac508296a35dacbd4ea43512986a2b34b6ce9c0c0f5e`.
- Reproduction manifest: [`eval/final_answer_eval_manifest.json`](../eval/final_answer_eval_manifest.json); it records candidate and dev hashes, seed, quotas, selected IDs, and corpus hash.
## Dataset and isolation

- Final set: 45 cases: 25 multi-hop/cross-document HotpotQA cases, 5 direct single-hop cases, 8 synthetic unanswerable cases, and 7 synthetic conflict fixtures.
- The 38 live cases run through the production service path. The 7 conflict cases use injected synthetic evidence with the production agent and citation/conflict validator; they do not measure database retrieval.
- The separate 200-question retrieval development set is used only for tuning and the one-question smoke option. Final gold answers are not sent to the agent.
- Answerable support coverage for all 30 live answerable cases was checked against the local corpus during dataset construction. The 25 selected candidates and the five single-hop source facts are drawn from the prior indexed 40/40 candidate coverage check (92/92 support references). Before any final Gemini call, the CLI now repeats a read-only Frankfurt project, 50,000-document, and complete support-coverage preflight.
- Synthetic unanswerable identifiers were checked absent from the local generated corpus. No synthetic conflict documents were written to Supabase.

## Retrieval configuration comparison

Final-run settings are the existing defaults: BGE-small, semantic/keyword/hybrid modes, OR full-text keyword retrieval, equal-weight hybrid RRF (1.0/1.0, k=60), agent tool limit 4, and maximum 5 Gemini HTTP requests per investigation. The metrics below will use the same 30 answerable cases per mode; unanswerable cases remain in answer-quality metrics but not Recall@K/MRR.

| Mode | Recall@5 | Recall@10 | MRR | Median investigation | p95 investigation | Completed / 38 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Semantic | pending | pending | pending | pending | pending | 0 / 38 |
| Keyword | pending | pending | pending | pending | pending | 0 / 38 |
| Hybrid | pending | pending | pending | pending | pending | 0 / 38 |

## Answer quality and safety metrics

| Mode | Correct / completed | Answer-span match | Strict exact match | Answered accuracy | Abstention precision / recall | Citation validity | Retrieved support coverage |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Semantic | 0 / 0 | pending | pending | pending | pending / pending | pending | pending |
| Keyword | 0 / 0 | pending | pending | pending | pending / pending | pending | pending |
| Hybrid | 0 / 0 | pending | pending | pending | pending / pending | pending | pending |

Conflict fixture result: 0 / 0 correct detections; pending unless the isolated Gemini fixture run completed.

## Metric definitions

- Retrieval Recall@5/10 and MRR are supporting-title metrics over deduplicated chunks returned by the investigation's search-tool calls in order, assigned a cumulative first-seen investigation rank. The denominator is the complete-support answerable cases actually completed for each mode.
- Answer-span match is a normalized contiguous token match of the gold answer within the verified central claim. Strict exact match requires the normalized central claim to equal the gold answer. Both are automated string-match proxies, not entailment judgments.
- Overall correctness counts correct abstentions for the 8 unanswerable cases and requires an `answered` status plus answer-span match for answerable cases. Predicted answer, abstention, and conflict statuses are also counted separately.
- Citation validity is accepted citations divided by citations emitted in the model's draft. The existing validator checks retrieved chunk IDs and exact quote presence after whitespace normalization; it does not prove claim entailment.
- Supporting evidence coverage is the fraction of gold title/sentence references whose title and normalized sentence occur in retrieved chunks.

## API usage and checkpoint

- Final comparison plan: 121 investigations; maximum 605 Gemini HTTP requests. Historical Phase 3 examples used 3 and 5 requests each (only two observations), so 363–605 requests is a rough planning range, not a prediction.
- Completed result rows: 0. The runner fsyncs each investigation reservation and result. On resume, an incomplete final JSONL row is discarded while its reservation remains uncertain; requests without a result are not automatically retried.
- Local result/checkpoint file: `C:\Users\user\Desktop\Upgaming-AI\reports\final_evaluation_results.jsonl` (Git-ignored).
- Local `INVESTIGATION_DAILY_BUDGET`: 0; The configured local value is 0 and live calls are disabled. The Frankfurt Blueprint value is `sync: false`; its production value and Gemini provider quota were not accessible here. This CLI ledger only coordinates local evaluation runs; it is not a durable global cap shared with Render.

## Historical retrieval-only reference (200-question dev set)

These are previously measured Phase 6A retrieval results, not Phase 7 answer metrics and not a substitute for the pending final comparison.

| Mode / variant | Recall@5 | Recall@10 | MRR | Median latency | p95 latency |
| --- | ---: | ---: | ---: | ---: | ---: |
| Semantic | 0.8425 | 0.8775 | 0.927881 | 660.919 ms | 1,079.142 ms |
| OR keyword baseline | 0.2350 | 0.3625 | 0.254454 | 1,572.944 ms | 8,821.469 ms |
| Equal-weight hybrid baseline | 0.7475 | 0.8550 | 0.764548 | 2,245.356 ms | 9,756.986 ms |
| Informative-term keyword (0.05) | 0.2950 | 0.4550 | 0.342272 | 272.986 ms | 1,642.982 ms |

## Failure analysis

No Phase 7 live failure examples exist yet. After an approved run, the report will include sanitized case IDs, questions, failure labels, support-reference coverage, and validator diagnostics without retrieved text. These are diagnostic signals; answer-span mismatches still require review against verified citations before being called factual errors.

## Reproduction

```powershell
.\.venv\Scripts\python.exe -m scripts.prepare_final_eval
.\.venv\Scripts\python.exe -m scripts.evaluate_final
.\.venv\Scripts\python.exe -m scripts.evaluate_final --check-indexed-coverage
.\.venv\Scripts\python.exe -m scripts.evaluate_final --live --dev-smoke --confirm-api-usage
.\.venv\Scripts\python.exe -m scripts.evaluate_final --live --final --confirm-api-usage
```

The live commands require a positive local `INVESTIGATION_DAILY_BUDGET`; `--final` requires explicit API-usage confirmation and a fresh read-only Frankfurt corpus/evidence preflight. The first live step should be the one-question dev smoke. Review its request count and provider quota before approving the final run.

## Current preflight evidence

- The deterministic dataset builder passed: 45 cases and 62/62 answerable support references in the local generated corpus. The candidate pool SHA-256 matches the prior corpus audit; selected candidate answers were copied unchanged.
- The previous read-only production coverage report records 40/40 candidates and 92/92 support references in the indexed corpus. A new Frankfurt query was attempted but did not return a result in this workstation session; current live coverage is not independently verified.
- `pytest -q`: 224 passed. The limited development smoke command was blocked before model loading, database connection, or Gemini requests because the local daily budget is 0.
- No full final evaluation, production write, schema change, deployment, or held-out Gemini call was performed.
