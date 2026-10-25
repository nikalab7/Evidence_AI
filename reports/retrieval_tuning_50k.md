# Phase 6A: Retrieval Tuning on the 50K Corpus

## Scope and safety

- Database target was the Frankfurt Supabase project `nldnpqhqrfwjgxcqeuru`; the application's fail-closed project guard matched the target.
- Only the 200 development questions in `eval/retrieval_dev.jsonl` were read for diagnosis, tuning, and selection. All 200 had complete indexed supporting evidence. The 40 held-out candidates were not opened or used.
- Database work was read-only. No schema, index, ingestion, Gemini, API route, or UI changes were made.
- The corpus remained at 50,000 documents. PostgreSQL was 17.11 with pgvector 0.8.2; the existing FTS index is `chunks_tsv_gin_idx`.
- Retrieval quality is measured by supporting-title Recall@K and MRR under the established evaluation definitions. It is not answer correctness or factual entailment.

## Baseline

The recorded Phase 5 baseline used top K=10, candidate K=20, and equal-weight RRF (`k=60`).

| Mode | Recall@5 | Recall@10 | MRR | Median latency | p95 latency |
| --- | ---: | ---: | ---: | ---: | ---: |
| Semantic | 0.8425 | 0.8775 | 0.927881 | 660.919 ms | 1,079.142 ms |
| OR keyword | 0.2350 | 0.3625 | 0.254454 | 1,572.944 ms | 8,821.469 ms |
| Equal-weight hybrid | 0.7475 | 0.8550 | 0.764548 | 2,245.356 ms | 9,756.986 ms |

A separate fresh OR profile before query changes measured 759.677 ms median and 4,790.647 ms p95. This differs from both the recorded baseline and the later full tuning pass, so latency comparisons below are explicitly tied to their run. The three slowest queries in that profile took 17,184.445 ms, 14,057.258 ms, and 9,420.751 ms.

## SQL diagnosis before changing retrieval behavior

I ran `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` against the exact parameterized original OR search for the three slow dev queries, at candidate limit 20. Plans were captured after the profile pass with shared buffers warm; plan execution time is not cold-cache or end-user latency.

| Development query | Profile latency | Plan time: planning / execution | GIN rows and heap rows | Planner estimate | Ranking/sorting | Buffer and temp I/O |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| Sadat X / Egyptian president | 17,184.445 ms | 23.121 / 557.564 ms | 10,002 / 10,002 | 250 rows | `ts_rank_cd` top-N heapsort, 78 KiB; sort node 554.451 ms | 91,589 shared hits, 0 reads; 0 temp I/O |
| Holes / One Magic Christmas | 14,057.258 ms | 4.273 / 857.517 ms | 20,427 / 20,427 | 250 rows | `ts_rank_cd` top-N heapsort, 105 KiB; sort node 857.397 ms | 182,021 shared hits, 0 reads; 0 temp I/O |
| Zhang Jinghui / puppet state | 9,420.751 ms | 2.246 / 1,171.660 ms | 24,774 / 24,774 | 250 rows | `ts_rank_cd` top-N heapsort, 102 KiB; sort node 1,171.541 ms | 218,870 shared hits, 0 reads; 0 temp I/O |

All three used `chunks_tsv_gin_idx` via Bitmap Index Scan and Bitmap Heap Scan. There were no rows removed by index recheck, no lossy heap blocks, and no sequential scan. The main result filter removed no candidate rows. Each match caused document primary-key and indexed provenance lookups, repeated 10,002, 20,427, and 24,774 times. The recursive term-fold CTE had 7, 8, and 12 lexemes and took about 1 ms or less. There was no disk sort or temporary I/O.

**Diagnosis:** broad OR matching contributes materially to latency. It matches about 20% to 50% of this 50K corpus for the slow examples, while the planner estimated 250 matches, an underestimate of roughly 40x to 99x. PostgreSQL then scores and sorts every match and performs document/provenance lookups across the matched set. The GIN index is working; the measured work is broad match ranking and joins. The profile outliers were much slower than the later warm plans, showing that plan execution alone does not explain all observed latency variation.

No bounded-candidate strategy was added. Limiting unsorted or partially ranked rows could drop evidence, and the diagnosis did not establish a relevance-preserving bound. Informative-term filtering provides a measured selective path without an arbitrary limit.

## Informative-term strategy

The legacy OR strategy remains available and remains the default for existing callers. The additive `informative` strategy:

1. Uses PostgreSQL's English `to_tsvector` analysis for stemming and stopword removal.
2. Reads the already analyzed `pg_stats` most-common lexeme and frequency arrays for `chunks.tsv`; it does not compute a corpus-wide frequency count for each search.
3. Protects query tokens containing uppercase letters or digits (including named entities, acronyms, and numeric identifiers), maps them through the same English stemming, and keeps those lexemes regardless of frequency.
4. Keeps other lexemes below a configured estimated corpus-frequency threshold. Lexemes absent from the statistics are retained. If filtering would remove every lexeme, it falls back to the original OR term set.
5. Keeps all query data parameterized. The Python tokenizer only identifies protected tokens; it does not split or concatenate user text into SQL.

The frequency values in `pg_stats` are sampled statistics, not exact per-query document counts. Thresholds 0.05, 0.10, and 0.15 were compared on all 200 development questions. Selection prioritized Recall@10, then Recall@5, then MRR, then lower p95 latency. The 0.05 threshold was selected.

## Full 200-question evaluation: keyword and semantic

Successful tuning pass: one reused Frankfurt connection, exactly 200 eligible questions, top K=10 and candidate K=20. Semantic embedding and retrieval, keyword retrieval, and ranking timings exclude initial database connection/model loading. One earlier run with a 30-second statement timeout was canceled; the completed retry used a bounded 60-second statement timeout and had no query timeouts.

Latency p95 values use nearest-rank calculation, matching the project evaluation runner.

| Variant | Recall@5 | Recall@10 | MRR | Median latency | p95 latency |
| --- | ---: | ---: | ---: | ---: | ---: |
| Semantic | 0.8425 | 0.8775 | 0.927881 | 689.086 ms | 1,078.672 ms |
| A. Original OR keyword | 0.2350 | 0.3625 | 0.254454 | 1,284.109 ms | 6,939.861 ms |
| B. Informative, threshold 0.05 | 0.2950 | 0.4550 | 0.342272 | 272.986 ms | 1,642.982 ms |
| Informative, threshold 0.10 | 0.2500 | 0.3900 | 0.280440 | 444.041 ms | 1,603.321 ms |
| Informative, threshold 0.15 | 0.2475 | 0.3800 | 0.270482 | 474.034 ms | 1,584.743 ms |

The three lowest-ranked examples for each informative threshold still included the Yamba Football Club state question, the Ragnarok/Hela location question, and the University of Virginia/Nebraska founding comparison; none retrieved a supporting title in the top 10. More aggressive filtering did not resolve these cases.

At 0.05, keyword Recall@10 improved by 0.0925 and MRR by 0.087817 against the same-pass original OR run; median latency fell by 1,011.123 ms and p95 by 5,296.879 ms. Those are measured results on the development set, not a guarantee for other data or query distributions. Compared with the recorded baseline, the fresh original-OR run itself was also faster (1,284 vs. 1,573 ms median), so the threshold comparison uses the same-pass values above.

Examples from the three originally slow queries:

- **Improved:** “Were the films ‘Holes’ and ‘One Magic Christmas’ released in different years?” Original OR found neither supporting title in its top 10 (Recall@10 0, MRR 0). Threshold 0.05 retrieved “One Magic Christmas” by rank 5 (Recall@10 0.5, MRR 0.2).
- **Unchanged:** “Rapper Sadat X is named for the third President of Egypt, who was?” Both methods had Recall@5 0.5, Recall@10 1.0, and MRR 0.333333.
- **Still failing:** “Zhang Jinghui is well known for his role as second and final Prime Minister of a puppet state located where?” Both methods had zero recall at 5 and 10. The entity protection did not make this multi-hop evidence retrievable in the top 10.

The 0.05 variant still has substantially lower recall than semantic search (0.455 vs. 0.8775 at 10). It improves keyword search but does not make keyword-only retrieval the recommended default.

## Hybrid RRF grid

All grid rows use semantic weight 1.0 and the same per-question semantic and threshold-0.05 keyword candidate lists (candidate K=20). Each list was fetched once per grid pass; the eight configurations reused those lists, so retrieval SQL was not repeated per configuration. Grid latency is the sum of the measured sequential semantic call, informative keyword call, and that configuration's measured RRF fusion call on a reused connection. It includes query embedding and retrieval work, but excludes connection establishment, initial model load, and API overhead. The zero-keyword rows perform the keyword fetch for comparability, but their ranking is semantic-only.

| Semantic weight | Keyword weight | RRF k | Recall@5 | Recall@10 | MRR | Median latency | p95 latency |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1.0 | 0.00 | 20 | 0.8425 | 0.8775 | 0.927881 | 1,360.085 ms | 5,955.959 ms |
| 1.0 | 0.00 | 60 | 0.8425 | 0.8775 | 0.927881 | 1,360.018 ms | 5,955.896 ms |
| 1.0 | 0.25 | 20 | 0.8450 | 0.8725 | 0.904048 | 1,360.105 ms | 5,956.036 ms |
| 1.0 | 0.25 | 60 | 0.8250 | 0.8725 | 0.865762 | 1,360.067 ms | 5,955.985 ms |
| 1.0 | 0.50 | 20 | 0.8250 | 0.8725 | 0.856131 | 1,360.132 ms | 5,956.004 ms |
| 1.0 | 0.50 | 60 | 0.8175 | 0.8725 | 0.841595 | 1,360.104 ms | 5,955.992 ms |
| 1.0 | 1.00 | 20 | 0.7700 | 0.8625 | 0.795095 | 1,360.787 ms | 5,956.055 ms |
| 1.0 | 1.00 | 60 | 0.7700 | 0.8625 | 0.791762 | 1,360.075 ms | 5,955.989 ms |

The strongest **positive-keyword-weight** hybrid was weight 0.25 with `k=20`: it gained 0.0025 Recall@5 over semantic-only, but lost 0.0050 Recall@10 and 0.023833 MRR. Its measured median/p95 were about 1.36/5.96 seconds, versus 0.689/1.079 seconds for standalone semantic retrieval. Larger keyword weights regressed quality further. The grid's zero-weight rows match semantic-only quality and are not considered a true hybrid configuration.

A concrete high-keyword-weight regression: for “What is the cup series' name of the tournament who follows that other tournament that was founded in 1953?”, semantic-only retrieved one of the two supporting titles in its top 10 (Recall@10 0.5, MRR 0.142857). Equal-weight RRF with `k=20` returned neither (Recall@10 0, MRR 0).

## Recommendation

Use **semantic-only** as the default retrieval mode for this 50K corpus and this 200-question development set. It has the strongest Recall@10 and MRR and much lower measured latency than a hybrid retrieval call. Keep informative keyword search (threshold 0.05), legacy OR keyword search, and weighted hybrid available for explicit demonstrations and evaluation. The existing engine default was left unchanged for backwards compatibility; this report records the recommended operating choice, not a runtime default switch.

## Reproduction and limitations

From the repository root:

```powershell
.\.venv\Scripts\python.exe scripts/evaluate_retrieval_tuning.py
.\.venv\Scripts\python.exe -m pytest -q
```

Final verification: `pytest -q` passed **131 tests**. `py_compile` passed for the changed Python modules and `git diff --check` reported no whitespace errors.

The tuning script fails closed unless the database project reference matches Frankfurt, the corpus has exactly 50,000 documents, and all 200 development questions have complete indexed evidence. It only opens `eval/retrieval_dev.jsonl`; it does not load the 40 held-out candidates. Database access is read-only.

Limitations: timings varied materially between runs; the reported latency is for a reused local connection and does not include network connection setup or service/API overhead. `pg_stats` frequencies are sampled. The selected threshold was chosen on the development set and should not be treated as held-out evidence. The FTS change improves keyword retrieval but leaves keyword-only recall well below semantic retrieval. Exact title-level retrieval metrics do not establish factual entailment.
