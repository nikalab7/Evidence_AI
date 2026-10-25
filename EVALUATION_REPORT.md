# EvidenceAI Evaluation Report

## Evaluation status

The original 45-case final evaluation completed. This report preserves its
Phase 7.3 measurements and separates a later seven-conflict post-hoc rerun.
Metrics below are the recorded results in
[reports/final_evaluation.md](reports/final_evaluation.md).

## Dataset and separation

The final answer set contains 45 cases:

| Category | Cases | Evaluation path |
| --- | ---: | --- |
| Multi-hop/cross-document HotpotQA | 25 | Live investigation pipeline |
| Direct single-hop HotpotQA | 5 | Live investigation pipeline |
| Synthetic unanswerable | 8 | Live investigation pipeline |
| Synthetic conflicting evidence | 7 | Injected fixture evidence; no database retrieval |

The 200-question retrieval-development set is separate and was used for
retrieval tuning and development checks. The final gold answers were not passed
to the agent. No final answer cases were used to tune the prompt or retrieval
weights.

The indexed evidence preflight recorded 30/30 answerable final cases and 62/62
support references present in the Frankfurt corpus. Final retrieval-only
metrics use the same 30 answerable cases for all modes. The 40-candidate pool
is not the completed final set.

## Retrieval results

Retrieval-only comparison: top_k=10, candidate_k=20, equal hybrid weights and
RRF k=60. Metrics are supporting-title recall/MRR, not answer accuracy.

| Mode | Recall@5 | Recall@10 | MRR | Median latency | p95 latency | Cases |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Semantic | 0.8667 | 0.8833 | 0.9167 | 836.5 ms | 1,142.4 ms | 30/30 |
| Keyword | 0.2500 | 0.4333 | 0.3289 | 3,085.9 ms | 11,214.2 ms | 30/30 |
| Hybrid | 0.7667 | 0.8667 | 0.8344 | 3,674.0 ms | 11,789.4 ms | 30/30 |

Semantic was selected as the investigation default because it had the strongest
measured recall/MRR and the lowest median and p95 retrieval latency in this
comparison. Keyword and Hybrid remain implemented and selectable.

Historical 200-question development-set reference:

| Mode/variant | Recall@5 | Recall@10 | MRR | Median | p95 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Semantic | 0.8425 | 0.8775 | 0.927881 | 660.9 ms | 1,079.1 ms |
| OR keyword baseline | 0.2350 | 0.3625 | 0.254454 | 1,572.9 ms | 8,821.5 ms |
| Equal-weight Hybrid baseline | 0.7475 | 0.8550 | 0.764548 | 2,245.4 ms | 9,757.0 ms |
| Informative-term Keyword (0.05) | 0.2950 | 0.4550 | 0.342272 | 273.0 ms | 1,643.0 ms |

The development measurements came from a different cohort and configuration
history. Do not combine them with final-set values as if they were one run.
Detailed SQL diagnosis and tuning appear in
[reports/retrieval_tuning_50k.md](reports/retrieval_tuning_50k.md).

## Answer quality and evidence

Answer generation was measured with Semantic retrieval only. There were 38
production-path cases: 30 answerable and 8 unanswerable.

| Metric | Result | Denominator / interpretation |
| --- | ---: | --- |
| Overall correct | 27/38 (71.05%) | 19 correctly answered answerable cases + 8 correct abstentions |
| Answer-span match | 19/30 (63.33%) | Normalized gold-answer span in the verified central claim |
| Strict exact match | 0/30 | Central claim exactly equals normalized gold string |
| Answered-question accuracy | 19/25 (76.00%) | Correct answers among 25 cases the model answered |
| Abstention precision | 8/13 (61.54%) | Correct unanswerable abstentions among 13 total abstentions |
| Abstention recall | 8/8 (100%) | Correctly abstained on all eight synthetic unanswerable cases |
| Citation quote validity | 38/45 (84.44%) | Draft citations passing retrieved-chunk/exact-quote checks |
| Retrieved support coverage | 55/62 (88.71%) | Gold title/sentence references found in retrieved evidence |

Category scores: multi-hop/cross-document 14/25; single-hop 5/5; synthetic
unanswerable cases 8/8. The model produced 25 answered, 13 abstained, and zero
conflicting statuses in the 38 production-path cases.

The 45-citation denominator is draft citations across the 38 production-path
investigations, not 45 investigations. A citation passes only when its chunk
was retrieved and the quote appears verbatim after whitespace normalization.
This verifies source-text presence, not whether the source entails the claim.

## Conflicts and Phase 7.4 post-hoc check

The original final run recognized 1/7 conflict fixtures. Six returned
INSUFFICIENT because an explicitly empty central claim was rejected before the
validator considered fully cited conflict groups. Phase 7.4 retained a narrow
validator fix, selected using independent development fixtures.

| Run | Conflict detections | Exact quote checks | Gemini HTTP attempts | Median / p95 |
| --- | ---: | ---: | ---: | ---: |
| Original Phase 7.3 final run (frozen) | 1/7 | 14/14 | 23 | 2,631.6 / 3,984.7 ms |
| After Phase 7.4 fix, selected on dev fixtures only (post-hoc rerun) | 7/7 | 14/14 | 21 | 3,121.7 / 3,305.1 ms |

This seven-case row is a post-hoc regression comparison, not a new independent
final benchmark. The final fixtures were not used to select or tune the fix.
Exact quote checks do not establish that the model correctly recognized a
logical contradiction. One earlier approved attempt failed on all seven
fixtures with upstream network errors after 14 request attempts and produced no
model output; it is excluded. The later rerun proceeded only after the separate
Gemini service probe passed. The source report records both attempts.

## Latency and model usage

| Work | Median | p95 | Gemini HTTP requests |
| --- | ---: | ---: | ---: |
| 38 production-path final investigations | 4,622.4 ms | 7,273.0 ms | 139 |
| Original seven conflict fixtures | 2,631.6 ms | 3,984.7 ms | 23 |
| Post-hoc seven conflict rerun | 3,121.7 ms | 3,305.1 ms | 21 |

The original 45 cases used 162 Gemini HTTP requests total. The post-hoc rerun
used 21 additional requests; the service probe was separate and is excluded
from investigation totals. The selected model was gemini-3.5-flash-lite.

## Failure analysis

- **Multi-hop relation failure:** the DHL question asked for a co-founder whose
  business partner had a son convicted of manslaughter. All five support
  references were retrieved, but the answer selected Adrian Dalsey based on
  his own son's conviction instead of preserving the business-partner relation
  to Larry Hillblom. This is a reasoning/relationship-binding error, not a
  retrieval miss.
- **Retrieval misses:** the Stainton film question retrieved one of two support
  references; the Marie-Barbe de Boullongne continent question also retrieved
  one of two.
- **Abstention and citations:** diagnostic categories overlap. The run recorded
  five answerable abstentions, including retrieval misses, citations rejected
  by the strict validator, and model abstentions despite complete retrieved
  support.
- **Conflict handling:** original conflict groups could not be recovered for
  the six failed baseline fixtures. Phase 7.4 replay diagnosed the empty-central
  claim path using independent development drafts; exact quote matching still
  cannot prove contradiction semantics.
- Recorded diagnostic categories overlap: incorrect multi-hop reasoning (5),
  invalid/missing citation (3), model abstention (2), and retrieval miss (6).
  These counts are diagnostic tags, not mutually exclusive totals.

Final answer-span match and retrieval recall are separate measures. The former
is an automated text proxy; neither metric is a human factual-entailment
assessment. The final benchmark is small, and final answer quality was not run
for Keyword or Hybrid.

## Reproduction and source records

The exact dataset hash, generation settings, metric definitions, checkpoint
counts, and detailed case-level analysis remain in
[reports/final_evaluation.md](reports/final_evaluation.md). Phase 7.4
development diagnosis and replay evidence are in
[reports/phase7_4_quality_improvement.md](reports/phase7_4_quality_improvement.md).
The original result file and evaluation data are unchanged and remain governed
by their repository ignore/tracking rules.
