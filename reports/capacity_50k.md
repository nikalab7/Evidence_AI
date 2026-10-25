# Phase 5 - Full 50K Corpus Ingestion

**Status: complete; final capacity gate passed.** The live Supabase database identified by the fail-closed connection guard as Frankfurt project nldnpqhqrfwjgxcqeuru contains the approved 50,000-document corpus. Mindo and the Sydney EvidenceAI project were not written to. This milestone made no schema, retrieval algorithm, Gemini, or UI changes and ran no destructive SQL.

## Configuration and reproducibility

- Dataset: hotpotqa/hotpot_qa, distractor train split, revision 1908d6afbbead072334abe2965f91bd2709910ab; datasets 4.8.4; sample seed 42.
- Input: the first 50,000 stable unique documents in data/corpus.jsonl (50,000 distinct IDs and normalized content hashes; file SHA-256 3dd75ba39fd8fe6842bf5cbc186da8457c7f3d90cba6cc6e98b44e63df7de0b). Corpus and credentials are Git-ignored.
- Existing optimized schema and paragraph chunker; BAAI/bge-small-en-v1.5; 384-dimensional embeddings stored in halfvec(384); four local embedding threads. Render remains configured for one thread.
- Batch size: 100; integrity/capacity checkpoints every 500 documents. Stages used detached PowerShell processes with persistent stdout/stderr and process-status files under ignored reports/phase5_logs/; each detached process was verified alive after launch.
- Database identity was checked before writes; the CLI rejects any project reference other than the approved Frankfurt project and refuses unexpected schema/security/index state. Existing documents were matched against the same corpus prefix before resuming.

### Commands

Run the current completed checkpoint's zero-insert verification:

~~~powershell
.\.venv\Scripts\python.exe scripts\ingest_phase5.py --limit 50000 --threads 4
~~~

For a first staged run from the already verified 1,000-document baseline, run each command in order and advance only after the prior process logs stage_complete with continue_allowed: true:

~~~powershell
.\.venv\Scripts\python.exe scripts\ingest_phase5.py --limit 10000 --threads 4
.\.venv\Scripts\python.exe scripts\ingest_phase5.py --limit 25000 --threads 4
.\.venv\Scripts\python.exe scripts\ingest_phase5.py --limit 40000 --threads 4
.\.venv\Scripts\python.exe scripts\ingest_phase5.py --limit 50000 --threads 4
~~~

Evaluate the 200-question dev set with the same candidate settings (held-out candidates are not passed to this command):

~~~powershell
.\.venv\Scripts\python.exe scripts\evaluate_retrieval.py --top-k 10 --candidate-k 20 --semantic-weight 1 --keyword-weight 1 --rrf-k 60 --details-json reports\phase5_logs\retrieval_50k_200_attempt2.details.json
~~~

Run the complete automated suite:

~~~powershell
.\.venv\Scripts\python.exe -m pytest -q
~~~

Repeat the read-only complete-evidence coverage check for dev and held-out candidate files:

~~~powershell
@'
import json
from pathlib import Path
from app.db.connection import EXPECTED_SUPABASE_PROJECT_REF, connect_database
from app.db.queries import read_indexed_source_evidence
from app.evaluation.metrics import indexed_evidence_pairs, select_eligible_questions
for filename in ("eval/retrieval_dev.jsonl", "eval/eval_candidates.jsonl"):
    questions = [json.loads(line) for line in Path(filename).read_text(encoding="utf-8").splitlines() if line.strip()]
    with connect_database() as conn:
        evidence = read_indexed_source_evidence(conn)
    eligible, excluded = select_eligible_questions(questions, indexed_evidence_pairs(evidence))
    print(EXPECTED_SUPABASE_PROJECT_REF, filename, len(eligible), "/", len(questions), "missing", len(excluded))
'@ | .\.venv\Scripts\python.exe -
~~~

The evaluator rechecks complete supporting evidence from indexed source titles, sentence arrays, and reconstructed paragraph text before scoring. The separate final-candidate coverage check used the same read-only evidence-pair validator against eval/eval_candidates.jsonl; it did not run retrieval or send those records to the investigation agent.

## Stage and capacity checkpoints

Database and relation measurements are bytes, after ANALYZE at the stage boundary. [Projection +25%] is the CLI's extrapolation of target-relation storage to 50K plus the required safety margin. The database threshold is 450,000,000 bytes.

At intermediate stages, a projected final size over 450,000,000 bytes stops the next stage. At 50K, an actual size at or below 450,000,000 bytes passes; 450,000,001 through 499,999,999 bytes is a warning pending review; 500,000,000 bytes or more is a critical stop with writes halted. The measured final size falls in the pass range.

| Stage target | New docs | New provenance | New chunks | Elapsed (s) | Embedding (s) | DB bytes after ANALYZE | EvidenceAI relations | HNSW | GIN | halfvec values | 50K projection +25% | Gate |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 10,000 | 9,000 | 9,003 | 9,000 | 2,627.007 | 1,998.873 | 71,587,507 | 60,096,512 | 11,714,560 | 4,939,776 | 7,760,000 | 389,966,944 | continue |
| 25,000 | 15,000 | 15,002 | 15,000 | 3,277.652 | 2,294.948 | 160,052,915 | 148,348,928 | 29,270,016 | 10,731,520 | 19,400,000 | 385,502,304 | continue |
| 40,000 | 15,000 | 15,006 | 15,000 | 2,948.559 | 2,032.268 | 245,274,291 | 233,996,288 | 46,825,472 | 15,015,936 | 31,040,000 | 379,716,704 | continue |
| 50,000 | 10,000 | 10,006 | 10,000 | 2,132.031 | 1,293.589 | 304,797,363 | 293,298,176 | 58,523,648 | 19,406,848 | 38,800,000 | 380,996,704 | passed |

Stage time sums to **10,985.249 s (3.05 h)** for 49,000 new documents, an observed end-to-end ingestion throughput of **4.461 documents/s** including model startup, database writes, ANALYZE, and verification. Embedding generation totaled **7,619.678 s** (6.430 docs/s while embedding). This excludes pauses between detached processes and recovery checks.

At 40K, the measured 50K projection with margin was 379,716,704 bytes, below the 450 MB stop threshold; the linear pre-margin final-size estimate was 303,773,363 bytes, about 58.50 MB beyond the measured 40K database size. The final stage measured HNSW at 58,523,648 bytes and GIN at 19,406,848 bytes, so the indexes remained within the capacity projection. HNSW was maintained by inserts; no index was dropped or rebuilt.

### Per-batch checkpoint log

Every 500-document checkpoint recorded the live document count, database size, 50K projection including the 25% margin, and WAL size. All checkpoint entries are included here so the ignored process logs are not required to understand the stage history.

| Stage target | Live documents | DB bytes | Projected 50K +25% bytes | WAL bytes |
| ---: | ---: | ---: | ---: | ---: |
| 10,000 | 1,500 | 21,837,491 | 437,521,504 | 67,109,227 |
| 10,000 | 2,000 | 24,155,827 | 416,529,504 | 83,886,443 |
| 10,000 | 2,500 | 27,006,643 | 402,449,504 | 83,886,443 |
| 10,000 | 3,000 | 30,234,291 | 405,009,504 | 83,886,443 |
| 10,000 | 3,500 | 33,183,411 | 401,864,362 | 83,886,443 |
| 10,000 | 4,000 | 36,296,371 | 401,241,184 | 83,886,443 |
| 10,000 | 4,500 | 39,130,803 | 398,974,732 | 83,886,443 |
| 10,000 | 5,000 | 41,883,315 | 394,359,904 | 83,886,443 |
| 10,000 | 5,500 | 44,652,211 | 391,278,595 | 83,886,443 |
| 10,000 | 6,000 | 47,716,019 | 391,707,744 | 100,663,659 |
| 10,000 | 6,500 | 50,566,835 | 390,092,975 | 100,663,659 |
| 10,000 | 7,000 | 53,507,763 | 389,513,459 | 100,663,659 |
| 10,000 | 7,500 | 56,489,651 | 389,352,544 | 100,663,659 |
| 10,000 | 8,000 | 59,659,955 | 390,683,744 | 100,663,659 |
| 10,000 | 8,500 | 62,527,155 | 389,629,627 | 100,663,659 |
| 10,000 | 9,000 | 65,787,571 | 391,423,300 | 100,663,659 |
| 10,000 | 9,500 | 68,490,931 | 389,363,324 | 100,663,659 |
| 10,000 | 10,000 | 71,587,507 | 389,966,944 | 100,663,659 |
| 25,000 | 10,500 | 74,372,787 | 388,660,125 | 100,663,659 |
| 25,000 | 11,000 | 77,502,131 | 389,427,018 | 117,440,875 |
| 25,000 | 11,500 | 80,336,563 | 388,524,440 | 117,440,875 |
| 25,000 | 12,000 | 83,072,691 | 387,185,078 | 134,218,091 |
| 25,000 | 12,500 | 85,890,739 | 386,362,464 | 134,218,091 |
| 25,000 | 13,000 | 88,995,507 | 386,981,590 | 134,218,091 |
| 25,000 | 13,500 | 91,674,291 | 385,582,708 | 134,218,091 |
| 25,000 | 14,000 | 94,402,227 | 384,503,173 | 134,218,091 |
| 25,000 | 14,500 | 97,662,643 | 385,793,262 | 134,218,091 |
| 25,000 | 15,000 | 100,472,499 | 385,120,012 | 134,218,091 |
| 25,000 | 15,500 | 103,159,475 | 383,994,713 | 134,218,091 |
| 25,000 | 16,000 | 105,838,259 | 382,907,744 | 134,218,091 |
| 25,000 | 16,500 | 108,787,379 | 382,910,654 | 134,218,091 |
| 25,000 | 17,000 | 111,400,627 | 381,678,568 | 134,218,091 |
| 25,000 | 17,500 | 114,292,403 | 381,511,630 | 134,218,091 |
| 25,000 | 18,000 | 117,405,363 | 382,121,967 | 134,218,091 |
| 25,000 | 18,500 | 120,993,459 | 384,304,502 | 134,218,091 |
| 25,000 | 19,000 | 123,819,699 | 383,866,060 | 134,218,091 |
| 25,000 | 19,500 | 126,539,443 | 383,108,770 | 134,218,091 |
| 25,000 | 20,000 | 129,578,675 | 383,387,744 | 134,218,091 |
| 25,000 | 20,500 | 132,372,147 | 382,903,843 | 134,218,091 |
| 25,000 | 21,000 | 135,206,579 | 382,564,888 | 134,218,091 |
| 25,000 | 21,500 | 137,991,859 | 382,098,814 | 134,218,091 |
| 25,000 | 22,000 | 141,293,235 | 383,120,108 | 134,218,091 |
| 25,000 | 22,500 | 145,159,859 | 385,666,144 | 134,218,091 |
| 25,000 | 23,000 | 147,855,027 | 384,918,179 | 134,218,091 |
| 25,000 | 23,500 | 150,599,347 | 384,332,767 | 134,218,091 |
| 25,000 | 24,000 | 153,523,891 | 384,241,078 | 134,218,091 |
| 25,000 | 24,500 | 156,087,987 | 383,233,623 | 134,218,091 |
| 25,000 | 25,000 | 159,839,923 | 385,236,064 | 134,218,091 |
| 40,000 | 25,500 | 162,764,467 | 384,876,259 | 134,218,091 |
| 40,000 | 26,000 | 165,533,363 | 384,412,139 | 134,218,091 |
| 40,000 | 26,500 | 168,154,803 | 383,617,758 | 134,218,091 |
| 40,000 | 27,000 | 170,784,435 | 382,871,763 | 150,995,307 |
| 40,000 | 27,500 | 173,463,219 | 382,264,603 | 150,995,307 |
| 40,000 | 28,000 | 176,527,027 | 382,538,557 | 150,995,307 |
| 40,000 | 28,500 | 178,902,707 | 381,695,540 | 150,995,307 |
| 40,000 | 29,000 | 181,761,715 | 381,519,298 | 150,995,307 |
| 40,000 | 29,500 | 184,432,307 | 380,949,844 | 150,995,307 |
| 40,000 | 30,000 | 187,127,475 | 380,450,572 | 150,995,307 |
| 40,000 | 30,500 | 190,461,619 | 381,277,045 | 150,995,307 |
| 40,000 | 31,000 | 194,172,595 | 382,667,147 | 150,995,307 |
| 40,000 | 31,500 | 196,753,075 | 381,941,223 | 150,995,307 |
| 40,000 | 32,000 | 199,628,467 | 381,813,984 | 150,995,307 |
| 40,000 | 32,500 | 202,176,179 | 381,060,508 | 150,995,307 |
| 40,000 | 33,000 | 204,879,539 | 380,624,652 | 150,995,311 |
| 40,000 | 33,500 | 207,615,667 | 380,262,940 | 150,995,311 |
| 40,000 | 34,000 | 210,474,675 | 380,137,749 | 150,995,311 |
| 40,000 | 34,500 | 213,194,419 | 379,763,898 | 150,995,311 |
| 40,000 | 35,000 | 215,774,899 | 379,152,042 | 150,995,311 |
| 40,000 | 35,500 | 218,478,259 | 378,773,759 | 150,995,311 |
| 40,000 | 36,000 | 221,345,459 | 378,690,429 | 150,995,311 |
| 40,000 | 36,500 | 224,114,355 | 378,441,053 | 167,772,527 |
| 40,000 | 37,000 | 227,161,779 | 378,668,904 | 167,772,527 |
| 40,000 | 37,500 | 230,512,307 | 379,395,852 | 167,772,527 |
| 40,000 | 38,000 | 233,690,803 | 379,820,722 | 167,772,527 |
| 40,000 | 38,500 | 237,426,355 | 381,138,868 | 167,772,527 |
| 40,000 | 39,000 | 240,236,211 | 380,939,728 | 167,772,527 |
| 40,000 | 39,500 | 242,767,539 | 380,304,922 | 167,772,527 |
| 40,000 | 40,000 | 245,495,475 | 379,993,184 | 167,772,527 |
| 50,000 | 40,500 | 247,912,115 | 379,273,604 | 167,772,527 |
| 50,000 | 41,000 | 250,681,011 | 379,041,114 | 167,772,527 |
| 50,000 | 41,500 | 253,408,947 | 378,752,540 | 167,772,527 |
| 50,000 | 42,000 | 256,472,755 | 378,970,648 | 167,772,527 |
| 50,000 | 42,500 | 260,667,059 | 380,846,117 | 167,772,527 |
| 50,000 | 43,000 | 263,501,491 | 380,701,412 | 167,772,527 |
| 50,000 | 43,500 | 266,163,891 | 380,312,862 | 167,772,527 |
| 50,000 | 44,000 | 268,916,403 | 380,061,142 | 167,772,527 |
| 50,000 | 44,500 | 271,881,907 | 380,081,318 | 167,772,527 |
| 50,000 | 45,000 | 274,609,843 | 379,806,589 | 184,549,743 |
| 50,000 | 45,500 | 277,411,507 | 379,639,173 | 184,549,743 |
| 50,000 | 46,000 | 280,164,019 | 379,408,614 | 184,549,743 |
| 50,000 | 46,500 | 282,850,995 | 379,094,928 | 184,549,743 |
| 50,000 | 47,000 | 285,628,083 | 378,907,744 | 184,549,743 |
| 50,000 | 47,500 | 288,544,435 | 378,907,744 | 184,549,743 |
| 50,000 | 48,000 | 291,624,627 | 379,121,078 | 184,549,743 |
| 50,000 | 48,500 | 294,819,507 | 379,477,807 | 184,549,743 |
| 50,000 | 49,000 | 299,488,947 | 381,708,072 | 184,549,743 |
| 50,000 | 49,500 | 301,962,931 | 381,123,929 | 184,549,743 |
| 50,000 | 50,000 | 304,576,179 | 380,720,224 | 184,549,743 |

## Final storage measurement

A post-stage, zero-insert idempotence rerun re-checked all expected corpus rows and ran ANALYZE. It inserted **0 documents, 0 provenance rows, and 0 chunks**. The final pg_database_size measurement was **304,576,179 bytes (304.576 MB / 290.47 MiB)**, below the 450,000,000-byte gate. The final 50K +25% projection was 380,720,224 bytes; the SQL-based WAL reserve estimator left 317,211,961 bytes of safe-budget headroom.

This headroom is a conservative SQL estimate using the configured 2 GiB disk budget, a 95% safe-use limit, and a 1.25 GiB WAL reserve. It is **not** a live Supabase physical-disk dashboard measurement; that dashboard was not accessible during this run.

| Relation | Rows | Heap bytes | Index bytes | Total relation bytes |
| --- | ---: | ---: | ---: | ---: |
| documents | 50,000 | 36,052,992 | 12,697,600 | 48,963,584 |
| document_sources | 50,018 | 43,827,200 | 15,278,080 | 59,465,728 |
| chunks | 50,000 | 79,552,512 | 97,501,184 | 184,868,864 |
| **EvidenceAI total** |  |  |  | **293,298,176** |

| Index / storage measure | Bytes |
| --- | ---: |
| chunks_embedding_hnsw_idx (HNSW) | 58,523,648 |
| chunks_tsv_gin_idx (GIN) | 19,406,848 |
| Half-vector values (pg_column_size; excludes row overhead and HNSW) | 38,800,000 |
| Other EvidenceAI indexes, combined | 47,521,792 |
| Database bytes outside the three EvidenceAI relations | 11,278,003 |

The final stage's post-ANALYZE database size was 304,797,363 bytes; the subsequent zero-insert verification measured 304,576,179 bytes, a **221,184-byte decrease**. The reason is undetermined; no cause is asserted.

## Final integrity and security results

- Counts: **50,000 documents; 50,018 provenance/source rows; 50,000 paragraph chunks**.
- Exact corpus comparison: all 50,000 documents, 50,018 sources, and 50,000 chunks matched the generated corpus on final verification.
- Orphan chunks: **0**; orphan sources: **0**; invalid offsets: **0**; embeddings with dimensions other than 384: **0**.
- Unicode-safe chunk reconstruction was verified by exact comparison of offset slices against source paragraph text across the corpus. Unit fixtures cover Unicode and repeated-text boundaries.
- Stable IDs were verified against the same corpus. A fresh DB connection read back the final state. Idempotent rerun inserted zero rows of every type.
- Supporting-evidence coverage from live indexed source/chunk text: eval/retrieval_dev.jsonl **200/200 (100%)**; eval/eval_candidates.jsonl **40/40 (100%)**. Held-out candidates were used only for this coverage check, not retrieval tuning or agent calls.
- Project/schema checks: target ref nldnpqhqrfwjgxcqeuru; only public relations chunks, document_sources, documents; RLS enabled; backend-only grants verified; pgvector 0.8.2; HNSW and GIN indexes valid. No migration, table drop, index drop/rebuild, or schema change occurred.
- Capacity result: **PASS** (actual database size 304,576,179 bytes, less than 450,000,000 bytes).

## Retrieval evaluation

All **200/200** development questions had complete document-and-sentence evidence and were scored. The evaluator used BGE-small, candidate K=20, output K=10, equal-weight RRF (semantic=1, keyword=1, k=60). Latency is per question: semantic includes query embedding plus semantic SQL retrieval; keyword is OR-FTS SQL retrieval; hybrid includes both retrieval calls and RRF. The benchmark reuses a database connection and loaded model, so connection establishment and model initialization are excluded. No Gemini generation or answer-entailment metric is included.

| Mode | Questions | Recall@5 | Recall@10 | MRR | Median ms | p95 ms | 1K baseline R@5 / R@10 / MRR | 50K on matched 82: R@5 / R@10 / MRR | Matched-82 change R@5 / R@10 / MRR |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |
| Semantic | 200 | 0.8425 | 0.8775 | 0.927881 | 660.919 | 1079.142 | 0.9329 / 0.9756 / 0.9817 | 0.8415 / 0.8780 / 0.946864 | -0.091437 / -0.097551 / -0.034836 |
| Keyword | 200 | 0.2350 | 0.3625 | 0.254454 | 1572.944 | 8821.469 | 0.5915 / 0.7866 / 0.5351 | 0.1951 / 0.3476 / 0.225469 | -0.396378 / -0.439039 / -0.309631 |
| Hybrid | 200 | 0.7475 | 0.8550 | 0.764548 | 2245.356 | 9756.986 | 0.8232 / 0.9573 / 0.8555 | 0.7622 / 0.8476 / 0.776829 | -0.061005 / -0.109739 / -0.078671 |

The direct regression comparison uses the same **82 questions** previously eligible in the 1K corpus and the same top K, candidate K, and RRF settings. All three modes regressed on this matched cohort, most sharply OR-keyword search. The separate all-200 figures above are the full development-set results. Retrieval relevance is supporting-title match; exact retrieval/citation matching does not prove factual entailment or answer correctness. Parameters were not tuned against the 40 held-out candidates.

### Example misses (full 200-question development set)

### Hybrid retrieval

- Question (5a78eb0155429974737f78ff): What is the cup series' name of the tournament who follows that other tournament that was founded in 1953?
- Supporting titles: Sony Open in Hawaii, Tournament of Champions (golf)
- Top five titles: Monster Energy NASCAR Cup Series, CAF Super Cup, List of CAF Super Cup winners, Geordie Shore (series 7), FA Cup
- Example metrics: Recall@5=0, Recall@10=0, MRR=0. Overall mode: Recall@5=0.7475, Recall@10=0.8550, MRR=0.764548.
### Keyword retrieval

- Question (5a70f2b25542994082a3e41f): What Australian state is home to the Yamba Football Club?
- Supporting titles: Yamba FC, Yamba, New South Wales
- Top five titles: Sedan Cambrai Football Club, Western Magpies Australian Football Club, West Australian Football Club, Paul Johnson (Australian footballer, born 1984), Friends Club
- Example metrics: Recall@5=0, Recall@10=0, MRR=0. Overall mode: Recall@5=0.2350, Recall@10=0.3625, MRR=0.254454.
### Semantic retrieval

- Question (5a7e247b5542995ed0d166aa): What child actress appeared in a film based on the character Sir John Falstaff?
- Supporting titles: Beatrice Welles, Chimes at Midnight
- Top five titles: Disney's The Kid, Matilda (1996 film), Michael Fassbender, Natascha McElhone, Alice in Wonderland (2010 film)
- Example metrics: Recall@5=0, Recall@10=0, MRR=0. Overall mode: Recall@5=0.8425, Recall@10=0.8775, MRR=0.927881.


## Errors, retries, and limitations

- One Stage B connection attempt failed before stage_started, so it made no writes. Five read-only connection/SELECT 1 checks then succeeded; Stage B resumed from the verified 10K checkpoint with idempotent inserts.
- Stage B completed and logged its passing checkpoint, but the PowerShell controller received a null ExitCode and paused. The completion event was checked; the controller was corrected, and execution continued at 25K without replaying inserts.
- The first full retrieval-evaluation attempt failed to establish the database connection and emitted no metrics. Five read-only connection checks succeeded, and a second run completed. The first attempt's stderr contains only a sanitized OperationalError classification.
- A fresh final coverage query was initially blocked by the workstation sandbox's outbound-network rule. It was rerun as an authorized read-only check and returned 200/200 dev and 40/40 held-out coverage; no data was written.
- Small monitoring helper errors (unsupported PowerShell null-coalescing syntax and a local JSON/Decimal conversion) affected monitoring output only; they caused no database changes.
- The 221,184-byte size decrease between the final stage and idempotence measurement is unexplained. Physical disk usage was not measured from the Supabase dashboard.
- Keyword and hybrid p95 retrieval latencies are high; results are reported without tuning. Retrieval metrics are title-level and do not establish answer correctness or entailment.

Detached stdout/stderr/process files and full per-question evaluation details remain local and Git-ignored under reports/phase5_logs/. This report contains the stage checkpoints, aggregate results, and notable failures needed to audit the run.
