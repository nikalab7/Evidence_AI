# Phase 1E — Dedicated Supabase and Optimized Schema

Date: 2026-10-24

Status: verified on the dedicated Evidence_AI Supabase project,
`csenhlrsttuukzwglttf`. This report covers only the first 1,000 corpus records.

Historical snapshot from 2026-10-24, before the approved Frankfurt region
migration. The current database target and replacement measurements are in
`reports/region_migration.md`; this report's Sydney measurements remain a
historical baseline.

## Project isolation and safety

The previous local `DATABASE_URL` pointed to the Mindo Supabase project
(`umbayvfikvxjzhxojofn`), which also contains another application's tables.
EvidenceAI now rejects database URLs whose Supabase project reference is not
`csenhlrsttuukzwglttf`. This Phase 1E run connected only to Evidence_AI; it did
not connect to, write to, or delete anything from Mindo.

Before the first write, the URL-derived project reference matched the approved
ID, PostgreSQL identified the target as `postgres`, and the public schema had
zero relations. No existing target data was present. The schema is additive;
no `DROP`, `TRUNCATE`, or `DELETE` was run. `pgvector` 0.8.2 was enabled in the
`extensions` schema on PostgreSQL 17.11.

## Schema and access controls

- `documents.full_text` is the canonical text. JSONB `metadata` retains
  application-specific fields; fields confirmed to duplicate normalized
  document/source columns were removed from that JSONB object.
- `document_sources` retains every stable source ID, title alias, normalized
  title, URL, revision, split, sentence array, and document relationship.
- `chunks` stores stable IDs, strategy/position, Unicode character offsets,
  `halfvec(384)`, model name, and a per-chunk `tsv`; it stores no duplicate
  `chunk_text`. Retrieval reconstructs text with PostgreSQL `substring`.
- Each `tsv` gives title aliases weight A and chunk body weight B, using the
  English text-search configuration. A GIN index supports chunk-level search.
  Source/title and document-text triggers refresh affected chunk vectors.
- HNSW uses `halfvec_cosine_ops` and is created only after all 1,000 documents,
  1,001 sources, and 1,000 chunks have loaded. `ANALYZE` runs after index
  creation.
- RLS is enabled on all three tables. `PUBLIC`, `anon`, and `authenticated`
  have no table privileges; this was checked for SELECT, INSERT, UPDATE,
  DELETE, TRUNCATE, REFERENCES, and TRIGGER. `service_role` has the intended
  backend table privileges and `BYPASSRLS`. The local direct database URL is a
  backend-only secret and is not stored in Git.

The FTS update trigger was exercised by temporarily changing one source title
inside a transaction, confirming its unique token appeared with weight A, and
rolling the transaction back. No probe title remained afterward. A read-only
rebuild comparison found zero stored-`tsv` mismatches.

## 1,000-record load and verification

The first run loaded the same first 1,000 unique records from
`data/corpus.jsonl` using BAAI/bge-small-en-v1.5 with four local threads. A
post-load check initially exited on the server's `vector_dims(halfvec)` function
name; the schema and inserted rows remained intact. After correcting that
function call, the full ingestion command was rerun. It passed all row checks
and inserted zero duplicate documents, sources, or chunks.

The successful idempotence run reported:

| Check | Result |
| --- | ---: |
| Documents | 1,000 |
| Provenance/source rows | 1,001 |
| Paragraph chunks | 1,000 |
| Orphan chunks / sources | 0 / 0 |
| Embeddings not 384-D | 0 |
| Invalid chunk offsets | 0 |
| Inserts on rerun: documents / sources / chunks | 0 / 0 / 0 |
| Fresh-connection verification | Passed |

The idempotent rerun compared every document and source row with the prepared
corpus and compared every reconstructed chunk, position, and offset. Unit tests
also cover Unicode and repeated paragraph text. The 82 eligible development
questions have complete title/sentence evidence in the indexed subset; the
other 118 of 200 are excluded because their complete evidence is not present.

The successful four-thread run spent 131.262 s generating 1,000 embeddings
(7.618 chunks/s); total runtime was 324.991 s, including model setup, database
checks, and verification. A process working-set sample during the run was about
1.48 GB; it was not a peak-RSS measurement. Render remains configured for one
embedding thread. The first HNSW build completed after bulk load, but its exact
build duration was not captured; the 1.674 s reported on the idempotent run is
the existing-index check plus `ANALYZE`, not an index build time.

## Measured storage after ANALYZE

Latest read-only snapshot: **18,454,195 B** database size. EvidenceAI's three
relations occupy **6,832,128 B** in total. The earlier successful ingestion
report measured 18,667,187 B while the EvidenceAI relation sizes were already
the same. The 212,992 B difference in whole-database size is unexplained; the
latest repeated database-size samples were stable at 18,454,195 B. No cause is
asserted. The whole-database size was not sampled during the empty preflight,
so an exact empty-to-full database-size delta is unavailable.

| Relation | Rows | Table storage | Indexes | Total relation size |
| --- | ---: | ---: | ---: | ---: |
| `documents` | 1,000 | 794,624 B | 245,760 B | 1,040,384 B |
| `document_sources` | 1,001 | 950,272 B | 368,640 B | 1,318,912 B |
| `chunks` | 1,000 | 1,851,392 B | 2,621,440 B | 4,472,832 B |

| Stored value/index | Size |
| --- | ---: |
| Halfvec values (`pg_column_size`) | 776,000 B (776 B average) |
| GIN `chunks_tsv_gin_idx` | 991,232 B |
| HNSW `chunks_embedding_hnsw_idx` | 1,179,648 B |

The table statistics showed `ANALYZE` completed for all three relations. The
database total includes PostgreSQL/Supabase objects beyond these EvidenceAI
relations.

### 10K/50K storage estimates

These are linear estimates from the measured 1K relation total, not capacity
tests. I treated the current non-EvidenceAI remainder (11,622,067 B) as fixed,
scaled the 1K EvidenceAI relations linearly, and added a **25% safety margin**
to that scalable portion. The model assumes the same one-paragraph document
shape, provenance ratio, metadata profile, GIN/HNSW index configuration, and
similar text lengths.

| Corpus size | Estimate without margin | Estimate with 25% margin |
| ---: | ---: | ---: |
| 10,000 | 79.94 MB | 97.02 MB |
| 50,000 | 353.23 MB | 438.63 MB |

These totals include the current non-EvidenceAI database remainder. Actual
future database overhead, longer text, index behavior, and platform limits may
differ; 50K has not been loaded or capacity-verified.

## Retrieval comparison

The prior baseline is the post-OR evaluation recorded in
`reports/hybrid_retrieval.md` against the former Mindo-backed 1K subset. Both
runs used the same 82 eligible questions, top K=10, candidate K=20, and
equal-weight RRF (1:1, k=60). Relevance is supporting-title match, not sentence
entailment or answer correctness.

| Mode | Baseline R@5 | Phase 1E R@5 | Baseline R@10 | Phase 1E R@10 | Baseline MRR | Phase 1E MRR |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Semantic | 0.9329 | 0.9329 | 0.9756 | 0.9756 | 0.9817 | 0.9817 |
| OR keyword | 0.3598 | 0.5915 | 0.5732 | 0.7866 | 0.3232 | 0.5351 |
| Equal-weight hybrid | 0.7378 | 0.8232 | 0.9268 | 0.9573 | 0.7418 | 0.8555 |

Keyword and hybrid retrieval improved on this subset after title aliases were
added at weight A. Semantic quality metrics were unchanged. Median latency was
higher on the new project: semantic 149.018→449.991 ms, keyword
131.429→421.830 ms, and hybrid 286.058→880.143 ms. This is a measured
approximately 3.0–3.2× latency regression; the cross-project timing does not
isolate network or service variance, so it is not attributed to one cause.

The HNSW-specific check confirmed the query plan used
`chunks_embedding_hnsw_idx`. Compared with an exhaustive halfvec scan on the
same vectors and 82 questions, HNSW had identical aggregate Recall@5, Recall@10,
and MRR. Top-10 sets and order matched for 81/82 questions; mean top-10 set
overlap was 0.9988. Median database-only latency was 389.497 ms for HNSW and
534.984 ms exhaustive in this run. One question therefore had a ranking change,
even though aggregate title metrics were unchanged.

Example of a remaining lexical miss: question `5a77f31055429949eeb29fbc`
(`What is the full name of the artist who recorded Me Enamore?`) had keyword
Recall@10 0.0; hybrid Recall@10 was 0.5 and MRR 0.2. The FTS weighting improved
aggregate results but did not eliminate off-target matches.

## Tests and reproduction

Full suite: **84 passed**. No dependencies were added. No API, UI, or Gemini
code was changed.

```powershell
.venv\Scripts\python.exe scripts\ingest_hotpotqa.py --limit 1000 --batch-size 25 --threads 4
.venv\Scripts\python.exe scripts\evaluate_retrieval.py --top-k 10 --candidate-k 20 --semantic-weight 1 --keyword-weight 1 --rrf-k 60
.venv\Scripts\python.exe scripts\benchmark_halfvec.py
.venv\Scripts\python.exe scripts\measure_db_size.py
.venv\Scripts\python.exe -m pytest -q
```

`connect_database()` rejects any direct or pooler URL that does not identify
project `csenhlrsttuukzwglttf`. Keep the production `DATABASE_URL` in the
backend environment only. Before any Render database-backed deployment, update
Render's secret to the Evidence_AI connection URL; the local `.env` update does
not change Render environment settings.
