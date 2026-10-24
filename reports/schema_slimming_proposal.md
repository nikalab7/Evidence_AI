# Phase 1E — Schema Slimming Proposal

Date: 2026-10-24

**Status: analysis and proposal only.** The database was queried read-only. No
tables, columns, indexes, rows, or extensions were changed; no documents were
ingested. Approval is still required before any destructive migration.

## Measured Supabase baseline

Read-only measurements against the live Supabase project:

| Measurement | Value |
| --- | ---: |
| Database size | 31,796,371 B (31.80 MB; 30.33 MiB) |
| `documents` rows | 1,000 |
| `document_sources` rows | 1,001 |
| `chunks` rows | 1,000 |
| Total size of the three project relations | 10,952,704 B |
| Relation indexes (`pg_indexes_size`) | 4,857,856 B |
| Vector values (`sum(pg_column_size(embedding))`) | 1,540,064 B |

| Relation | Table storage | Indexes | Total |
| --- | ---: | ---: | ---: |
| `documents` | 1,867,776 B | 245,760 B | 2,113,536 B |
| `document_sources` | 950,272 B | 368,640 B | 1,318,912 B |
| `chunks` | 3,276,800 B | 4,243,456 B | 7,520,256 B |

Largest indexes are `chunks_embedding_hnsw_idx` at **2,056,192 B** and
`chunks_tsv_gin_idx` at **1,736,704 B**. The three application relations
account for about 10.95 MB of the 31.80 MB database; the remaining database
size is not attributed to these tables.

### Text and metadata duplication

- All **1,000 of 1,000** paragraph rows have `documents.full_text =
  chunks.chunk_text`. `pg_column_size` summed to 532,842 B for `full_text` and
  522,893 B for `chunk_text`. The values are exactly equal; their measured
  stored sizes differ because PostgreSQL can store/compress the columns
  differently.
- `documents.metadata` totals 972,241 B. Its `source_variants` values account
  for 638,563 B and exactly match the relational source rows on all 1,000
  documents. Those rows already preserve every title alias and source sentence.
- Metadata also repeats `doc_id` (76,000 B), `content_hash` (76,000 B), `source`
  (62,000 B), `source_revision` (52,000 B), `source_split` (17,000 B), and
  `title` (31,739 B). Read-only comparisons confirmed these values match their
  normalized document/source fields for all 1,000 documents.
- `document_sources` contains 1,001 rows and 4,137 sentences. Its `sentences`
  payload is 567,522 B. This table remains the authoritative provenance record;
  none of its source IDs, URLs, revisions, splits, title aliases, or sentences
  should be removed.
- `chunks.tsv` occupies 665,273 B. It is indexed by the GIN index above. The
  current generated vector is built from chunk text only.

These `pg_column_size` sums are input to a projection model, not a promise of
equal disk reclamation. TOAST compression, tuple layout, index rebuilds, and
table rewrites affect the physical result.

## Halfvec evaluation

The installed pgvector version is **0.8.0**, and the live server accepted
read-only `halfvec` casts. pgvector documents `vector` values as four bytes per
dimension and `halfvec` values as two bytes per dimension. For 384 dimensions,
the approximate payloads are 1,544 B for `vector(384)` and 776 B for
`halfvec(384)`, including the type header. The measured current vector payload
averages 1,540.064 B per row. Substituting a 776 B halfvec value would save
about **764 B per row**, or **49.6% of the embedding-column values**. This
does not include a measured change to HNSW index size.

I ran `scripts/benchmark_halfvec.py` against the 1,000 current vectors. It
compared exhaustive full-precision distance ordering with distances after
casting both stored and query vectors to `halfvec(384)` in `SELECT` statements.
Index scans were disabled so this isolates quantization from HNSW approximation.
No halfvec column or index was created.

| Result | Full `vector` | Halfvec cast |
| --- | ---: | ---: |
| Evidence-eligible questions | 82 | 82 |
| Recall@5 | 0.9329 | 0.9329 |
| Recall@10 | 0.9756 | 0.9756 |
| MRR | 0.9817 | 0.9817 |
| Median DB search time | 275.389 ms | 278.532 ms |

The exact top-10 chunk set matched for **82/82** questions; the exact top-10
order matched for **81/82**. Title-level metrics were identical. This is useful
evidence that half precision did not change these 1K query results, but it does
not validate a halfvec HNSW index, 50K behavior, other models, or answer
entailment. The measured cast query did not become faster; it was an exhaustive
scan and is not a fair indexed latency comparison.

## HNSW, GIN, and the unexplained GIN growth

The current HNSW index occupies about **2.06 MB per 1,000 chunks**; a purely
linear 50K projection is about **102.8 MB**. The current GIN index occupies
about **1.74 MB per 1,000 chunks**; a purely linear 50K projection is about
**86.8 MB**. These index projections are already represented in the existing
whole-database storage slope and are not capacity guarantees.

For a fresh/staging corpus load, the proposal is to load rows first and build
the HNSW index after bulk ingestion. pgvector documents that HNSW has slower
builds and higher memory use than IVFFlat, and recommends adding indexes after
an initial bulk load when that workflow is available. Building later avoids
maintaining the graph for every inserted row; it does not reduce the final
index's storage requirement. Measure build time, peak memory, query plan, and
Recall@K on the actual Supabase tier before choosing this sequence. The current
live HNSW index will remain untouched.

The unexplained GIN movement remains unresolved:

- The first 1,000-document snapshot recorded a GIN index size of 1,089,536 B.
- A later read-only snapshot measured 1,736,704 B: an increase of 647,168 B.
- Over the same snapshots, total database size increased 851,968 B while row
  counts were unchanged. The `chunks` relation increased 655,360 B; the other
  two project relations were unchanged, leaving 196,608 B outside those three
  relation sizes.
- Current statistics show 1,000 live chunks, zero dead tuples, no recorded
  vacuum/autovacuum timestamp, and an autoanalyze timestamp. These statistics
  do not identify why the GIN index grew.

PostgreSQL documents that GIN can defer index-entry work to a pending list and
that vacuum/autoanalyze or a list threshold can move entries into the main
index. This is a possible mechanism, **not a verified explanation** for these
measurements. No before/after pending-list measurement was collected, so the
cause remains unknown. See [PostgreSQL GIN tips](https://www.postgresql.org/docs/current/gin-tips.html)
and [GIN implementation](https://www.postgresql.org/docs/current/gin-implementation.html).

## Local embedding-thread benchmark

`scripts/benchmark_embedding_threads.py` ran locally on Windows with Python
3.11.9, the project-local model cache, 64 fixed corpus paragraphs, and three
timed repetitions per isolated process. It used the same BGE model and kept
`local_files_only=True`. The application loader and Render configuration remain
at one thread.

| Local FastEmbed threads | Median time for 64 paragraphs | Throughput | Model initialization |
| ---: | ---: | ---: | ---: |
| 1 | 17.6337 s | 3.629 paragraphs/s | 0.2245 s |
| 2 | 11.0458 s | 5.794 paragraphs/s | 0.2548 s |
| 4 | 9.6075 s | 6.661 paragraphs/s | 0.2612 s |

On this machine, two threads were about 1.60× the one-thread throughput; four
threads were about 1.83×. Moving from two to four added about 15%. This small
sample is local-only and does not establish Render memory behavior. Keep
Render at one thread unless a separate Render measurement supports changing it.

## Proposed optimized schema

Keep the current logical entities and their CRUD/provenance responsibilities:

| Entity | Proposed retained data |
| --- | --- |
| `documents` | Stable `doc_id`/`content_hash`, canonical `full_text`, timestamps, and application-specific metadata only |
| `document_sources` | Every source ID, document link, title alias/normalized title, URL, revision, split, exact sentence array, timestamp |
| `chunks` | Stable chunk ID, document link, position/strategy, character offsets into canonical full text, per-chunk `tsv`, `halfvec(384)`, embedding model, timestamp |

Keep `documents.full_text` as the one canonical text copy. Replace duplicated
`chunks.chunk_text` with `start_char`/`end_char` offsets. Retrieval and citations
would select the exact chunk text as a substring of `documents.full_text`;
chunk IDs remain derived from the same reconstructed chunk text and position.
Store a per-chunk `tsv` computed from that substring during ingestion, rather
than a generated `tsv` that depends on a duplicate text column. This preserves
chunk-level GIN search for later multi-chunk documents. It requires exact
Unicode/offset tests and transactional refresh of offsets, `tsv`, and embeddings
whenever document content changes.

Keep `metadata` for arbitrary application metadata, but stop duplicating fields
that already live in normalized columns. A response serializer can reconstruct
the existing metadata view from `documents` and `document_sources`. Keep all
source rows and their sentences intact. Keep the GIN index on per-chunk `tsv`;
build HNSW on `halfvec(384)` only after the 1K precision test and a staged index
recall/build benchmark pass. The pgvector project documents half-precision
storage and HNSW operator classes in its [halfvec](https://github.com/pgvector/pgvector#half-precision-vectors)
and [HNSW](https://github.com/pgvector/pgvector#hnsw) sections.

The 1K corpus has one paragraph chunk per document, so moving the text to a
canonical document field is a direct mapping today. The offset design still
needs verification for multi-chunk files, repeated substrings, Unicode text,
updates, and exact citations before broader ingestion.

## 50K storage scenarios — estimates only

The existing capacity report estimates **507,281,896 B (507.3 MB)** from the
clean 100-to-1,000 insertion slope, and **554,518,789 B (554.5 MB)** using the
full observed size change that includes the unexplained growth. The following
scenarios subtract payload measurements scaled linearly from 1,000 rows. They
are steady-state estimates after any necessary table rewrite; they are not
benchmarked capacities.

| Scenario | Estimated savings at 50K | From 507.3 MB baseline | From 554.5 MB sensitivity case |
| --- | ---: | ---: | ---: |
| Halfvec column values only | 38.2 MB | 469.1 MB | 516.3 MB |
| Halfvec + duplicate metadata fields | 85.9 MB | 421.4 MB | 468.7 MB |
| Above + duplicate chunk text replaced by offsets | 112.0 MB | 395.3 MB | 442.5 MB |

The metadata estimate removes 953,302 B per 1K rows (`source_variants` and
confirmed duplicate metadata fields). The offset design removes a further
measured 522,893 B of duplicate chunk-text values per 1K. The halfvec estimate
uses the expected 776 B value against the measured 1,540.064 B vector average.
No HNSW-index savings are counted because the halfvec index has not been built
and measured. No GIN savings are counted. The combined 395–443 MB estimate is
conditional on all proposed changes and linear scaling; the 421–469 MB case is
the safer estimate if chunk-text deduplication is deferred. Full 50K capacity
remains unverified.

## Migration and rollback proposal

1. Before any change, take a recoverable backup/export and record database/table
   sizes, all row counts, source/chunk relationships, content hashes, vector
   dimensions, and the 82-question retrieval/citation baseline.
2. Rehearse at the current 1K limit in a separate staging schema or project.
   Add offsets, a shadow halfvec column, and a shadow per-chunk `tsv` while
   retaining all current columns and indexes. Backfill from the canonical text;
   verify every extracted chunk is byte-for-byte equal to its prior text and
   every provenance/sentence record remains present.
3. Build staged GIN/HNSW indexes, inspect plans and index sizes, and compare
   exact-vector vs halfvec Recall@5/10, MRR, top-10 order, and citation excerpts.
   Exercise document add/update/delete behavior on staging only.
4. Switch reads to the new columns only after these checks pass. Keep old data
   and indexes available through a rollback window. Before the 10K milestone,
   use the approved schema for the bulk load and build HNSW after that load if
   the measured build/memory results support it.
5. Request explicit approval before dropping old fields/indexes, stripping
   metadata keys, rewriting tables, or swapping/deleting legacy tables. Capture
   a fresh backup and a final row/hash/citation report immediately before that
   cutover.

Rollback before cleanup is to switch queries back to the current `vector`,
`chunk_text`, `tsv`, and metadata fields. Keep the original vector until the
rollback window closes: halfvec-to-vector casting cannot recover the lost
float32 precision. If old columns have been dropped, exact rollback requires a
backup or regenerating vectors and restoring removed metadata. Offsets can
reconstruct chunk text while canonical `full_text` remains.

Column drops do not immediately reclaim disk space in PostgreSQL. A rewrite is
needed for immediate reclamation, and `VACUUM FULL` holds an `ACCESS EXCLUSIVE`
lock. This means the projected savings are not available immediately after a
`DROP COLUMN`; plan temporary disk headroom and downtime before compaction. See
[ALTER TABLE](https://www.postgresql.org/docs/current/sql-altertable.html) and
[VACUUM](https://www.postgresql.org/docs/current/sql-vacuum.html).

## Potentially destructive operations — approval required

None of these operations was executed. Each requires explicit approval before
use:

- `UPDATE documents SET metadata = metadata - ...`: irreversibly removes
  JSONB keys unless the old payload is backed up.
- `ALTER TABLE public.chunks DROP COLUMN chunk_text`: removes stored text;
  offsets and citations must already be validated.
- `ALTER TABLE public.chunks DROP COLUMN tsv` and
  `DROP INDEX public.chunks_tsv_gin_idx`: removes the current keyword-search
  representation/index until a replacement is verified.
- `DROP INDEX public.chunks_embedding_hnsw_idx`: removes the current ANN path;
  queries may fall back to sequential scans until a replacement is built.
- `ALTER TABLE public.chunks ALTER COLUMN embedding TYPE
  extensions.halfvec(384) USING embedding::extensions.halfvec(384)`, or dropping
  the old vector after shadow-column validation: loses original float32 values.
- `DROP TABLE`, `TRUNCATE`, or `DELETE` on any existing project table; table
  swaps/renames that remove the old copy have the same approval gate.
- `VACUUM FULL` or a table-rewriting `ALTER TABLE` to reclaim dropped-column
  space: requires a table rewrite, lock time, and extra temporary disk space.
- Dropping a backup or legacy column after the rollback window is also a
  destructive cleanup step.

`documents.full_text`, `document_sources`, document IDs, title aliases, source
provenance, and supporting sentences are retained in the proposal. No schema
change or destructive action should proceed without the user's explicit
approval.

## Reproduction

Run from the repository root. The thread benchmark uses only the local corpus
and model cache. The halfvec benchmark uses read-only Supabase `SELECT`s and
does not create a column or index.

```powershell
.venv\Scripts\python.exe scripts\benchmark_embedding_threads.py --sample-size 64 --repeats 3 --threads 1 2 4
.venv\Scripts\python.exe scripts\benchmark_halfvec.py
.venv\Scripts\python.exe scripts\measure_db_size.py
.venv\Scripts\python.exe -m pytest -q
```
