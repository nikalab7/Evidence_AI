# Supabase and Render Region Migration

Date: 2026-10-25
Status: **Frankfurt database migration verified for the 1,000-document milestone; Render deployment remains pending**

## Target and safety gates

The configured Supabase endpoint resolves to project `nldnpqhqrfwjgxcqeuru` at `aws-1-eu-central-1.pooler.supabase.com` (Frankfurt region). The URL-derived project reference matches the fail-closed application guard. An earlier connection attempt was rejected; after the local database URI was corrected, the authenticated read-only gate passed. PostgreSQL identified database `postgres`, version 17.11. Before schema creation, the `public` schema contained zero tables, views, or other relations.

The Sydney Evidence_AI project (`csenhlrsttuukzwglttf`) remains the fallback and was not contacted during this migration. Mindo (`umbayvfikvxjzhxojofn`) was not contacted or modified. Only the Frankfurt project was accessed. The approved schema was applied additively; no `DROP`, `TRUNCATE`, or `DELETE` statement was run.

## Workstation connection latency

Sydney values are the previously recorded single-sample baseline. Frankfurt measurements were made before schema creation or corpus ingestion.

| Measurement | Sydney baseline | Frankfurt samples | Frankfurt min / median / max |
| --- | ---: | ---: | ---: |
| Fresh connection establishment | 2,496.3 ms (1 sample) | 5 | 427.68 / 440.54 / 1,573.84 ms |
| `SELECT 1` round trip | 810.6 ms (1 sample) | 25 | 66.13 / 69.63 / 396.53 ms |

The Frankfurt medians were about 82% lower for connection establishment and 91% lower for `SELECT 1` than the historical Sydney samples. This is a comparison to one old sample per measure, not a guarantee; Frankfurt also had long-tail outliers. These workstation tests do not measure Render-to-Supabase latency.

## Schema and corpus load

The optimized Phase 1E schema was applied to the empty Frankfurt `public` schema. PostgreSQL 17.11 has pgvector 0.8.2 in the `extensions` schema. Canonical text remains in `documents.full_text`; chunks use character offsets and `halfvec(384)`. The GIN FTS index and HNSW `halfvec_cosine_ops` index were present after loading; HNSW was created after the bulk load and the ingestion routine ran `ANALYZE` on all three tables.

The first 1,000 unique documents from the existing local corpus were loaded with BAAI/bge-small-en-v1.5, 384-dimensional embeddings, paragraph chunking, batches of 25, and four local embedding threads. The ordered document-ID manifest SHA-256 was `35612061e3396da9664c682a5e23aed5fa8a784ecd2ffc79e30ab1206c7815db`.

| Check | Actual result |
| --- | ---: |
| Documents / provenance rows / chunks | 1,000 / 1,001 / 1,000 |
| First-run inserts | 1,000 / 1,001 / 1,000 |
| Second identical run inserts | 0 / 0 / 0 |
| Orphan chunks / sources | 0 / 0 |
| Wrong embedding dimensions | 0 |
| Invalid chunk offsets | 0 |
| Document text mismatches vs corpus | 0 |
| Provenance mismatches vs corpus | 0 |
| Reconstructed chunk text mismatches | 0 |
| Stable IDs and exact Unicode reconstruction | Passed |
| Fresh-connection read verification | Passed |

All 82 evaluation questions classified as eligible had complete supporting title/sentence evidence in the indexed subset. The other 118 of 200 dev questions were excluded because their complete evidence is not present in the first 1,000 documents; they are not counted as retrieval failures.

The first load took 215.917 s total: 106.616 s embedding generation, 107.137 s database write and verification, and 0.686 s HNSW build. It embedded 1,000 chunks (9.379 chunks/s). The identical idempotence run took 240.887 s and inserted no rows.

## Storage and vector search

Sizes below are the actual post-load measurements after `ANALYZE`. The empty-project database already occupied 10,811,059 bytes; after migration it occupied 18,478,771 bytes, an observed increase of 7,667,712 bytes.

| Relation | Rows | Heap bytes | Index bytes | Total relation bytes |
| --- | ---: | ---: | ---: | ---: |
| `documents` | 1,000 | 745,472 | 245,760 | 1,040,384 |
| `document_sources` | 1,001 | 901,120 | 368,640 | 1,318,912 |
| `chunks` | 1,000 | 1,613,824 | 2,580,480 | 4,431,872 |

The HNSW index occupied 1,179,648 bytes; the chunk FTS GIN index occupied 950,272 bytes. `pg_column_size` reported 776,000 bytes total for the 1,000 halfvec values (776 bytes average), excluding row overhead and HNSW storage.

A real cosine-distance SQL benchmark used an independently embedded natural-language query, not a stored chunk vector. After two warmups, 10 searches had 75.725 ms minimum, 92.817 ms median, and 180.938 ms p95/maximum. The results were ordered by cosine distance. This is a query-latency check, not retrieval-quality evidence.

## Retrieval evaluation

The evaluation used the same 82 fully evidenced dev questions, BGE-small, candidate K=20, output K=10, and equal-weight RRF (`semantic=1`, `keyword=1`, `k=60`). The Sydney comparison is the verified Phase 1E run with the same optimized schema and title-weighted FTS. Metrics are title-level recall/MRR, not answer correctness or sentence entailment. The older Mindo-backed figures in `reports/hybrid_retrieval.md` are not used as the region baseline.

| Mode | Sydney Recall@5 | Frankfurt Recall@5 | Sydney Recall@10 | Frankfurt Recall@10 | Sydney MRR | Frankfurt MRR | Sydney median | Frankfurt median |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Semantic | 0.9329 | 0.9329 | 0.9756 | 0.9756 | 0.9817 | 0.9817 | 449.991 ms | 139.968 ms |
| OR keyword | 0.5915 | 0.5915 | 0.7866 | 0.7866 | 0.5351 | 0.5351 | 421.830 ms | 105.917 ms |
| Equal-weight hybrid | 0.8232 | 0.8232 | 0.9573 | 0.9573 | 0.8555 | 0.8555 | 880.143 ms | 252.653 ms |

Frankfurt latency p95 was 206.880 ms semantic, 204.077 ms keyword, and 403.321 ms hybrid. Aggregate retrieval metrics were unchanged between Sydney and Frankfurt Phase 1E. Frankfurt median retrieval latency was about 3.2x lower semantic, 4.0x lower keyword, and 3.5x lower hybrid. This cross-run comparison is descriptive; it does not isolate region from service load or workstation variability.

## Full investigation checks

The configured `gemini-3.5-flash-lite` model was used. Both checks stayed within the four-step/five-request limits.

| Outcome | Steps / tool calls | Gemini requests | DB connect | Retrieval total | Gemini summed latency | End-to-end | Verified citations |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Answered: Ironclad Board establishment year | 1 / 1 | 3 (all HTTP 200) | 0.656045 s | 0.398884 s | 2.775297 s | 4.253574 s | 1 |
| Abstained: Sadat X / third President of Egypt | 3 / 3 | 5 (all HTTP 200) | 0.700294 s | 1.136886 s | 3.379675 s | 5.612132 s | 0 |

The answered case validated the claim “The Ironclad Board was established in 1861” against chunk `fede37a5bca9624209d9c0a0d09cd6bd68023b0c7cf58469ad12e6343b2fb227`, with the exact source quote: “The Ironclad Board was an advisory board established by the Union in 1861 in response to the construction of the \"CSS Virginia\" by the Confederacy during the US Civil War.” Gemini used 4,515 total tokens for that run. The abstention run returned “Insufficient evidence” with no claims or citations and used 17,739 total tokens. Exact quote validation confirms that text exists in retrieved evidence; it does not prove entailment.

## Security and tests

All three expected tables have RLS enabled. `PUBLIC`, `anon`, and `authenticated` had no SELECT, INSERT, UPDATE, or DELETE privileges; `service_role` had the intended CRUD grants. No other public relations existed after schema setup. RLS is enabled but not forced; the backend database owner remains privileged, so the database URI must stay in backend-only secrets.

Full local suite: `.\.venv\Scripts\python.exe -m pytest -q` — **106 passed**. The existing Render service was not changed or deployed. Its live region remains unverified; `render.yaml` does not establish the region of an already-created service.

## Render preparation and next steps

`render.yaml` remains unchanged. `render.frankfurt.yaml` defines a distinct `evidence-ai-frankfurt` service in Frankfurt, with automatic deploys disabled and `DATABASE_URL`/`GEMINI_API_KEY` configured as secrets. It is prepared but has not been created or deployed. Render documents that service regions cannot be changed after creation, so use a new service/Blueprint with the custom file path and preserve the existing Sydney service: [Render regions](https://render.com/docs/regions), [Blueprint YAML reference](https://render.com/docs/blueprint-spec).

Before database-backed deployment, create the new Frankfurt service from `render.frankfurt.yaml`, set its Frankfurt `DATABASE_URL` secret and Gemini key, and verify the redacted database project reference. Then verify the actual service region, build logs for offline model-cache load, startup embedding check, peak memory, and `/health` HTTP 200. Do not delete or replace the existing Render service.

## Reproduction

From the project root with `.env` configured and the BGE cache present:

```powershell
.\.venv\Scripts\python.exe scripts/ingest_hotpotqa.py --limit 1000 --batch-size 25 --threads 4
.\.venv\Scripts\python.exe scripts/evaluate_retrieval.py --top-k 10 --candidate-k 20 --semantic-weight 1 --keyword-weight 1 --rrf-k 60
.\.venv\Scripts\python.exe scripts/investigate.py "What year was the Ironclad Board established?"
.\.venv\Scripts\python.exe scripts/investigate.py "Rapper Sadat X is named for the third President of Egypt, who was?"
.\.venv\Scripts\python.exe -m pytest -q
```
