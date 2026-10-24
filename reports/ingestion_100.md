# Phase 1C: Supabase Ingestion — 100 Documents

Date: 2026-10-24

Historical Phase 1C baseline from the Mindo Supabase project. That project was
not modified during Phase 1E; current Evidence_AI measurements are in
`reports/phase_1e_optimized.md`.

## Scope and implementation

The CLI read the first 100 unique content-addressed rows from the local,
Git-ignored `data/corpus.jsonl`. The full corpus has 50,000 unique IDs; the first
100 rows passed the content-hash and provenance checks. Each source paragraph
became one chunk using the plan's first strategy, paragraph-level chunking.
FastEmbed generated BAAI/bge-small-en-v1.5 embeddings locally in batches of 25.

The additive schema is in `migrations/schema.sql`: `documents` stores stable
content IDs, full text, and metadata; `document_sources` stores title aliases
and source provenance; `chunks` stores stable chunk IDs, source links, positions,
384-dimensional vectors, and a generated English `tsvector`. The schema adds
GIN and cosine-HNSW indexes. The CLI writes parameterized psycopg statements in
one transaction per batch and uses `ON CONFLICT DO NOTHING`; it validates
conflicting rows instead of overwriting them. No database rows were deleted or
updated.

## Real Supabase results

Before schema creation, the three target table names were absent. The live
database had pgvector 0.8.0 in the `extensions` schema and measured 20,491,411
bytes. The first ingestion run reported:

| Measurement | Before | After first run |
| --- | ---: | ---: |
| Database size | 20,491,411 B | 21,867,667 B |
| `documents` rows | 0 | 100 |
| `document_sources` rows | 0 | 100 |
| `chunks` rows | 0 | 100 |
| `documents` total relation size | 0 B | 319,488 B |
| `document_sources` total relation size | 0 B | 212,992 B |
| `chunks` total relation size | 0 B | 843,776 B |

The database-side verification found 100 target documents, 100 source/provenance
rows, 100 chunks, zero orphan chunks, and zero embeddings with dimensions other
than 384. A new psycopg connection independently read the inserted rows.

The real cosine-distance SQL query returned five rows in ascending distance
order. It used the first ingested paragraph's own embedding as the query vector:

| Rank | Cosine distance |
| ---: | ---: |
| 1 | 0.000000 |
| 2 | 0.330685 |
| 3 | 0.336954 |
| 4 | 0.356547 |
| 5 | 0.358464 |

This confirms pgvector SQL execution and ordering for this slice; it is not a
retrieval-quality or factual-entailment result.

## Idempotence and size observation

The same CLI command was rerun against the same 100 IDs. It inserted 0
documents, 0 source rows, and 0 chunks; all three tables remained at 100 rows.
The rerun's database size was 22,195,347 bytes both before and after that run.
A final read-only size check confirmed the same database size and row counts.

Between the first run's post-ingestion measurement (21,867,667 B) and the
rerun's pre-ingestion measurement (22,195,347 B), the database size differed by
327,680 bytes even though row counts remained 100. The final measured size is
1,703,936 bytes above the original baseline. Current total relation sizes are
319,488 B for `documents`, 212,992 B for `document_sources`, and 1,015,808 B
for `chunks`. The cause of the size difference between runs was not established;
no cause is attributed to the zero-insert rerun.

## Tests and limitations

The full suite passed: `48 passed`. Focused tests cover paragraph boundaries,
stable document/source/chunk IDs, metadata and aliases, embedding dimensions,
and conflict-safe idempotent writes.

This milestone covers only 100 HotpotQA paragraphs. It does not verify storage
capacity at 1,000 or 50,000 documents, compare the second chunking strategy,
implement file-upload parsers, or implement retrieval/Hybrid Search. Do not
extrapolate full-scale capacity from this sample. No later ingestion stage was
started.

## Reproduction commands

Run these commands in PowerShell from the repository root, with `DATABASE_URL`
configured in the ignored local `.env` and the BGE model cache available at
`.model_cache/`. The ingestion command is capped at exactly 100 unique documents
and does not accept a larger limit.

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe scripts\measure_db_size.py
.venv\Scripts\python.exe scripts\ingest_hotpotqa.py --batch-size 25
.venv\Scripts\python.exe scripts\ingest_hotpotqa.py --batch-size 25
.venv\Scripts\python.exe scripts\measure_db_size.py
```

The first ingestion execution inserts the rows; the second checks idempotence
and should report zero inserted documents, sources, and chunks.
