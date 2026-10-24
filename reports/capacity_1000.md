# Phase 1D — Supabase Capacity Test (1,000 Documents)

Date: 2026-10-24

Historical Phase 1D baseline from the Mindo Supabase project. That project was
not modified during Phase 1E; current Evidence_AI measurements are in
`reports/phase_1e_optimized.md`.

## Scope and safety

The existing paragraph chunker, `BAAI/bge-small-en-v1.5` FastEmbed model,
384-dimensional vectors, additive schema, and parameterized psycopg inserts
were reused. The CLI now accepts `--limit` with a default of 100 and a hard
maximum of 1,000. Before inserting, it reads existing document IDs and refuses
to write if any lie outside the selected corpus prefix or if the resulting
document count would exceed 1,000. The run did not execute destructive SQL,
change the schema, call Gemini, or use the API/UI.

The first 1,000 JSONL records were 1,000 unique content-addressed documents,
1,001 provenance records, and 1,000 paragraph chunks. Embeddings were generated
locally in batches of 25. The first execution inserted 900 new documents,
901 provenance records, and 900 chunks; the existing 100 were retained.

## Supabase results

| Snapshot | Database size | Documents | Provenance rows | Chunks |
| --- | ---: | ---: | ---: | ---: |
| Before Phase 1D (existing 100) | 22,195,347 B | 100 | 100 | 100 |
| After first 1,000-document run | 30,944,403 B | 1,000 | 1,001 | 1,000 |
| After zero-insert rerun and final probe | 31,796,371 B | 1,000 | 1,001 | 1,000 |

The first insertion run increased measured database size by **8,749,056 B**.
The final size is **9,601,024 B** above the initial 100-document snapshot;
the additional difference is investigated below and is not counted as a clean
per-document insertion cost.

Final table and index sizes after the rerun:

| Relation | Rows | Table storage | Indexes | Total relation size |
| --- | ---: | ---: | ---: | ---: |
| `documents` | 1,000 | 1,867,776 B | 245,760 B | 2,113,536 B |
| `document_sources` | 1,001 | 950,272 B | 368,640 B | 1,318,912 B |
| `chunks` | 1,000 | 3,276,800 B | 4,243,456 B | 7,520,256 B |
| **Total** | — | **6,094,848 B** | **4,857,856 B** | **10,952,704 B** |

`table_storage` is PostgreSQL `pg_table_size` (including TOAST); the index
column is `pg_indexes_size`. The per-index figures below are each index's main
fork from `pg_relation_size`; the aggregate is the authoritative complete index
size and can also include auxiliary forks.

| Index | Size |
| --- | ---: |
| `chunks_embedding_hnsw_idx` | 2,056,192 B |
| `chunks_tsv_gin_idx` | 1,736,704 B |
| `chunks_doc_id_chunking_strategy_chunk_position_key` | 147,456 B |
| `chunks_doc_id_idx` | 122,880 B |
| `chunks_pkey` | 155,648 B |

The measured vector-value storage was **1,540,064 B** for 1,000 embeddings,
averaging **1,540.06 B per vector**. This is `sum(pg_column_size(embedding))`;
it excludes row overhead and the HNSW index.

Database-side verification found 1,000 target documents, 1,001 target
provenance rows, and 1,000 target chunks; there were zero orphan source/chunk
rows and zero vectors with a dimension other than 384. A separate fresh
connection verified the same target counts after each run.

## Duration, throughput, and cosine SQL benchmark

First insertion run measurements:

| Stage | Duration |
| --- | ---: |
| Corpus read and preparation | 0.036 s |
| Model initialization | 0.250 s |
| Embedding 1,000 chunks | 202.707 s |
| Query embedding | 0.012 s |
| Database writes and verification | 50.747 s |
| End to end | 255.648 s |

This measured **4.933 embedded chunks/s**, **17.735 inserted documents per
database-phase second**, and **3.520 inserted documents per end-to-end second**
(900 documents inserted). These are local-run measurements for this machine
and dataset; the embedding stage ran locally, not on Render.

The cosine benchmark embedded the independent query “What events led to a
change in policy, and which organizations were affected?” with the same BGE
model, then ran 10 real PostgreSQL pgvector cosine-distance queries after 2
warmups. Each query returned five rows in ascending distance order. First-run
latency was **89.289 ms minimum, 117.289 ms median, and 242.328 ms maximum**.
The rerun median was **124.171 ms**, with one **1,076.815 ms** outlier; because
the p95 uses nearest-rank on 10 samples, p95 equals that maximum. The query
returned ranked distances, but no relevance labels were evaluated. This is a
SQL execution/latency check, not retrieval-quality evidence or factual
entailment evidence.

The idempotence rerun re-embedded locally, then reported **0 documents, 0
provenance rows, and 0 chunks inserted**. Counts stayed at 1,000 / 1,001 /
1,000. The database size measured at the start and end of that CLI's database
phase was 31,796,371 B. The rerun took 312.410 s overall, mostly from local
embedding generation; repeat runs currently recompute embeddings for existing
rows.

## Database-size discrepancy investigation

The Phase 1C report recorded a **327,680 B** difference between its first-run
database size (21,867,667 B) and a later 100-row measurement (22,195,347 B),
despite unchanged row counts. Its recorded target-relation totals changed from
1,376,256 B to 1,548,288 B: `chunks` increased by 172,032 B, while the other
two relation totals were unchanged. The remaining 155,648 B of database-size
change is not accounted for by those three relation totals. Earlier per-index
snapshots are unavailable, so the historical increase cannot be assigned to
a particular index or database activity.

During Phase 1D, the first post-insert database size was 30,944,403 B. Before
the idempotence command entered its database phase, a read-only probe observed
31,796,371 B. At that time `chunks` relation size was 655,360 B larger than in
the first post-insert snapshot, including a 647,168 B increase in the GIN
index; the other target relations were unchanged. The database total was
851,968 B larger, leaving 196,608 B outside the measured target-relation
increase. The idempotence command itself measured the same database size
before and after its database phase and inserted no rows.

PostgreSQL statistics after ingestion showed 1,000 live chunks, zero dead
tuples, 1,000 cumulative inserts, and zero updates/deletes. An autoanalyze
timestamp was present; no autovacuum timestamp was present. These observations
do not identify the cause of either size movement. Background database
activity, index page/pending-list maintenance, or measurement timing are
possible explanations, but none is established by the collected evidence.
No cause is attributed to the ingestion rerun. The size movement makes a single
point storage slope uncertain.

## 10K and 50K storage projections (estimates only)

For a clean insertion-only projection, the measured 100-to-1,000 database
increase was divided by the 900 new documents:

`8,749,056 B / 900 = 9,721.17 B per added document`.

Starting from the first post-insert 1,000-document database size of
30,944,403 B and extending that slope linearly:

| Target | Estimated total database size | Approximate binary size |
| --- | ---: | ---: |
| 10,000 documents | 118,434,963 B (118.4 MB) | 112.9 MiB |
| 50,000 documents | 507,281,896 B (507.3 MB) | 483.7 MiB |

As a sensitivity case, using the full 100-to-final size difference of
9,601,024 B / 900 (which includes the unexplained size movement) gives
approximately **127.8 MB at 10K** and **554.5 MB at 50K**. These are linear
estimates, not benchmarks or capacity verification. Index growth, TOAST,
background database activity, and paragraph-length variation may change the
actual result. The 50K estimates are near or above the plan's 500 MB storage
assumption, so the 50K capacity gate remains open; no 10K or 50K ingestion was
started.

## Tests and limitations

- Full test suite: `51 passed` (`.venv\Scripts\python.exe -m pytest -q`).
- Focused ingestion tests cover paragraph preservation, stable IDs, metadata
  and aliases, 384-dimensional embedding validation, insert-only idempotence,
  document-limit validation, the database-prefix safety guard, and the
  benchmark's no-quality-claim labeling.
- The 1,000-document Supabase milestone is verified. Full-scale storage,
  retrieval quality, Hybrid Search, Gemini RAG, and UI are not implemented or
  claimed.
- During the second local embedding run, Windows reported
  `PeakWorkingSet64 = 1,481,850,880 B` (about 1.38 GiB) for the Python process.
  This is local memory usage and is not a Render measurement.

## Reproduction commands

Run from the repository root with `DATABASE_URL` configured in the ignored
local `.env` and the existing BGE cache available. The first command writes
only the selected 1,000 unique documents; the second should report zero inserts
and verify the same final counts.

```powershell
.venv\Scripts\python.exe scripts\measure_db_size.py
.venv\Scripts\python.exe scripts\ingest_hotpotqa.py --limit 1000 --batch-size 25
.venv\Scripts\python.exe scripts\ingest_hotpotqa.py --limit 1000 --batch-size 25
.venv\Scripts\python.exe scripts\measure_db_size.py
.venv\Scripts\python.exe -m pytest -q
```
