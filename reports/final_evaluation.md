# Phase 7 — Final Evaluation & Quality Report

Evaluation status: **complete**

All planned cases have result rows. Metrics below are measured results from this run.

- Final dataset SHA-256: `d2663d7a8deaf573d8eaac508296a35dacbd4ea43512986a2b34b6ce9c0c0f5e`.
- Reproduction manifest: [`eval/final_answer_eval_manifest.json`](../eval/final_answer_eval_manifest.json); it records candidate and dev hashes, seed, quotas, selected IDs, and corpus hash.
## Dataset and isolation

- Final set: 45 cases: 25 multi-hop/cross-document HotpotQA cases, 5 direct single-hop cases, 8 synthetic unanswerable cases, and 7 synthetic conflict fixtures.
- The 38 live cases run through the production service path. The 7 conflict cases use injected synthetic evidence with the production agent and citation/conflict validator; they do not measure database retrieval.
- The separate 200-question retrieval development set is used only for tuning and the one-question smoke option. Final gold answers are not sent to the agent.
- Answerable support coverage for all 30 live answerable cases was checked against the local corpus during dataset construction. The 25 selected candidates and the five single-hop source facts are drawn from the prior indexed 40/40 candidate coverage check (92/92 support references). Before any final Gemini call, the CLI now repeats a read-only Frankfurt project, 50,000-document, and complete support-coverage preflight.
- Synthetic unanswerable identifiers were checked absent from the local generated corpus. No synthetic conflict documents were written to Supabase.

## Retrieval-only configuration comparison

This comparison uses only the same 30 answerable final cases, with no Gemini generation. Each mode uses top_k=10 and candidate_k=20; hybrid uses equal weights and RRF k=60. These retrieval metrics do not measure answer accuracy.

| Mode | Recall@5 | Recall@10 | MRR | Median retrieval | p95 retrieval | Questions |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Semantic | 0.8667 | 0.8833 | 0.9167 | 836.5 ms | 1142.4 ms | 30 / 30 |
| Keyword | 0.2500 | 0.4333 | 0.3289 | 3085.9 ms | 11214.2 ms | 30 / 30 |
| Hybrid | 0.7667 | 0.8667 | 0.8344 | 3674.0 ms | 11789.4 ms | 30 / 30 |

## Agent answer quality and safety metrics

Answer generation plan: `economical`. Only the modes below were sent through Gemini. In the economical plan, retrieval-only Keyword and Hybrid results are not answer-quality results.

| Mode | Completed / 38 | Median investigation | p95 investigation | Tool calls | Gemini HTTP requests |
| --- | ---: | ---: | ---: | ---: | ---: |
| Semantic | 38 / 38 | 4622.4 ms | 7273.0 ms | 65 | 139 |

| Mode | Correct / completed | Answer-span match | Strict exact match | Answered accuracy | Abstention precision / recall | Citation validity | Retrieved support coverage |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Semantic | 27 / 38 | 0.6333 | 0.0000 | 0.7600 | 0.6154 / 1.0000 | 0.8444 | 0.8871 |
- Semantic citation validation: 38 / 45 draft citations passed exact-quote checks.
- Semantic supporting evidence retrieved: 55 / 62 references.
- Semantic status counts: answered 25, abstained 13, conflicting 0.

| Category | Correct / cases | Answer-span matches / scored |
| --- | ---: | ---: |
| Multi-hop / cross-document | 14 / 25 | 14 / 25 |
| Single-hop | 5 / 5 | 5 / 5 |
| Unanswerable | 8 / 8 | not applicable |

Conflict fixtures: 1 / 7 correctly detected (0.1429); predicted statuses: conflicting 1, insufficient 6, answered 0.
The fixture agent made 23 Gemini requests and 9 tool calls; median/p95 latency 2631.6 ms / 3984.7 ms.
Exact-quote presence checks accepted 14 / 14 draft citations. This does not establish that the model recognized or correctly explained the contradiction.

## Metric definitions

- Retrieval Recall@5/10 and MRR are supporting-title metrics over deduplicated chunks returned by the investigation's search-tool calls in order, assigned a cumulative first-seen investigation rank. The denominator is the complete-support answerable cases actually completed for each mode.
- Answer-span match is a normalized contiguous token match of the gold answer within the verified central claim. Strict exact match requires the normalized central claim to equal the gold answer. Both are automated string-match proxies, not entailment judgments.
- Overall correctness counts correct abstentions for the 8 unanswerable cases and requires an `answered` status plus answer-span match for answerable cases. Predicted answer, abstention, and conflict statuses are also counted separately.
- Citation validity is accepted citations divided by citations emitted in the model's draft. The existing validator checks retrieved chunk IDs and exact quote presence after whitespace normalization; it does not prove claim entailment.
- Supporting evidence coverage is the fraction of gold title/sentence references whose title and normalized sentence occur in retrieved chunks.

## API usage and checkpoint

- Final `economical` plan: 45 investigations; maximum 225 Gemini HTTP requests. The rough planning range using 3–5 requests per investigation is 135–225; this is not a prediction.
- Completed result rows: 45. The runner fsyncs each investigation reservation and result. On resume, an incomplete final JSONL row is discarded while its reservation remains uncertain; requests without a result are not automatically retried.
- Measured Gemini HTTP requests in completed rows: 162 (production-path investigations: 139; conflict fixtures: 23).
- Batch stop reason: `none`.
- Local result/checkpoint file: `C:\Users\user\Desktop\Upgaming-AI\reports\final_evaluation_results.jsonl` (Git-ignored).
- Retrieval-only details: `C:\Users\user\Desktop\Upgaming-AI\reports\final_retrieval_comparison.json` (Git-ignored); this stage makes database retrieval calls only and uses no Gemini generation.
- Local `INVESTIGATION_DAILY_BUDGET`: 60; The configured local value is 60; the local journal limits this CLI to that rolling-24-hour count. The Frankfurt Blueprint value is `sync: false`; its production value was not accessible here. This CLI ledger only coordinates local evaluation runs; it is not a durable global cap shared with Render.

## Historical retrieval-only reference (200-question dev set)

These are previously measured Phase 6A retrieval results, not Phase 7 answer metrics.

| Mode / variant | Recall@5 | Recall@10 | MRR | Median latency | p95 latency |
| --- | ---: | ---: | ---: | ---: | ---: |
| Semantic | 0.8425 | 0.8775 | 0.927881 | 660.919 ms | 1,079.142 ms |
| OR keyword baseline | 0.2350 | 0.3625 | 0.254454 | 1,572.944 ms | 8,821.469 ms |
| Equal-weight hybrid baseline | 0.7475 | 0.8550 | 0.764548 | 2,245.356 ms | 9,756.986 ms |
| Informative-term keyword (0.05) | 0.2950 | 0.4550 | 0.342272 | 272.986 ms | 1,642.982 ms |

## Failure analysis

- Semantic diagnostic counts (categories may overlap): incorrect_multi_hop_reasoning 5, invalid_or_missing_citation 3, model_abstention 2, retrieval_miss 6.
- `semantic` `hotpotqa-5ab278cb554299449642c8b5` (multi_hop): 'What film other than the 2007 American computer-animated science fiction comedy film produced by Walt Disney Animation Studios was produced during Stainton's tenure?' - retrieval_miss; status `answered`; 1/2 support references; validator diagnostic `citations_verified`.
- `semantic` `hotpotqa-5ab8efc75542991b5579f05f` (multi_hop): 'What is the name of the co-founder of DHL whose business partner had a son convicted of manslaughter?' - incorrect_multi_hop_reasoning; status `answered`; 5/5 support references; validator diagnostic `citations_verified`.
- `semantic` `hotpotqa-5a7ebff35542994959419a6e` (multi_hop): 'Marie-Barbe de Boullongne was a philanthropist on what continent?' - retrieval_miss; status `answered`; 1/2 support references; validator diagnostic `citations_verified`.

## Reproduction

```powershell
.\.venv\Scripts\python.exe -m scripts.prepare_final_eval
.\.venv\Scripts\python.exe -m scripts.evaluate_final
.\.venv\Scripts\python.exe -m scripts.evaluate_final --check-indexed-coverage
.\.venv\Scripts\python.exe -m scripts.evaluate_final --live --dev-smoke --confirm-api-usage
.\.venv\Scripts\python.exe -m scripts.evaluate_final --live --final --comparison-plan economical --confirm-api-usage
.\.venv\Scripts\python.exe -m scripts.evaluate_final --live --final --comparison-plan full --confirm-api-usage
```

The live commands require a positive local `INVESTIGATION_DAILY_BUDGET`; `--final` requires explicit API-usage confirmation and a fresh read-only Frankfurt corpus/evidence preflight. The default economical plan uses semantic generation once per 38 live cases and once per seven conflict fixtures (45 total; maximum 225 Gemini requests), then runs a separate retrieval-only comparison on the same 30 answerable cases. `--comparison-plan full` preserves the 121-investigation, maximum-605-request three-mode answer evaluation.

## Current preflight evidence

- The deterministic dataset builder passed: 45 cases and 62/62 answerable support references in the local generated corpus. The candidate pool SHA-256 matches the prior corpus audit; selected candidate answers were copied unchanged.
- The optimized Frankfurt indexed-coverage gate passed in this run: 50,000 documents, 30/30 answerable cases, 62/62 exact support references, with 55 selected source/chunk rows read. This was a read-only check.
- The one approved development smoke completed in semantic mode: 1 search tool call, 3 Gemini HTTP requests, 5.261 seconds total. Retrieval ranked `Anwar Sadat` first; one of two drafted citations verified and one was rejected. The answer was not scored as a final evaluation result.
- A prior sandbox-only connection attempt failed before any Gemini call (0 requests); the authorized retry completed. Provider quota remaining could not be read from this workstation.
- Phase 7 final evaluation completed: all 45 cases have result rows (38 production-path cases and seven isolated conflict fixtures). No production writes, schema changes, deployment, or out-of-scope held-out Gemini calls were performed.

## Phase 7.3 execution details

- This authorized batch completed 36 new investigations (29 live Semantic cases and seven isolated conflict fixtures); the nine earlier completed cases were not rerun. The batch used 131 Gemini HTTP requests, below its 300-request authorization and the 180-request theoretical cap for 36 investigations. Across all 45 cases, 162 requests were recorded (139 live-path and 23 fixture requests). No HTTP 429, quota exhaustion, or investigation error occurred.
- Gemini quota figures were supplied by the operator (Tier 1: 4,000 RPM and 150,000 RPD); this run did not query the provider quota endpoint. The local `.env` budget was set to 60 for this evaluation only; Render configuration was not changed.
- Final answer metrics are Semantic-only. Retrieval-only Semantic, Keyword, and Hybrid comparison used the same 30 answerable final questions and made no Gemini requests. No ranking parameters or prompts were tuned against this held-out set.
