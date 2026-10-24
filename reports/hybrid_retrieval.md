# Phase 2 — Hybrid Retrieval

Date: 2026-10-24

Status: real semantic, PostgreSQL FTS, and Weighted RRF queries verified against
the existing Supabase 1,000-document subset. No documents were ingested and no
schema, API, Gemini, or UI changes were made.

## Implementation

- Semantic retrieval embeds a natural-language query locally with
  `BAAI/bge-small-en-v1.5`, validates its 384 finite dimensions, then orders
  rows by pgvector cosine distance.
- Keyword retrieval uses `websearch_to_tsquery('english', ...)`, the existing
  generated `tsv` column and GIN index, and `ts_rank_cd`.
- Weighted Reciprocal Rank Fusion is implemented in Python:

  `score(chunk) = α / (k + semantic_rank) + β / (k + keyword_rank)`

  Defaults are α=1, β=1, k=60. Fusion counts a chunk once per channel,
  merges provenance for chunks found by both channels, and breaks ties by
  earliest channel rank, then stable document and chunk IDs.
- The common `search(query, k, filters)` interface supports `semantic`,
  `keyword`, and `hybrid`; safe filters are `source_split`,
  `chunking_strategy`, and `embedding_model`. SQL values are bound parameters.
- Results include stable document/chunk IDs, title aliases, source provenance,
  a text excerpt, channel scores/ranks, and the final retrieval score.
- `scripts/retrieve.py` runs individual natural-language queries. The
  evaluation CLI runs only the evidence-eligible retrieval-dev cases.

## Evidence eligibility and evaluation method

The committed retrieval-dev file contains 200 HotpotQA questions. Eligibility
requires every supporting title/sentence pair to match normalized provenance
and to occur in an indexed paragraph chunk. Text matching applies the project's
Unicode normalization, case-folding, and whitespace collapse. This produced
**82 eligible questions**; the other **118 were excluded**, not scored as
retrieval misses. A post-run check joined 1,001 provenance rows to paragraph
chunks and confirmed 4,135 unique title/sentence pairs in chunk text.

Retrieval relevance is title-level: a hit is relevant when one of its source
title aliases exactly matches a gold supporting title after normalization.
Recall@K is the average fraction of gold supporting titles found in the top K;
MRR is the mean reciprocal rank of the first matching title. These metrics do
not assess answer correctness, sentence entailment, or factual support.

Evaluation used the same 1,000 indexed documents and 1,000 paragraph chunks for
all modes. Semantic and keyword channels each returned 20 candidates; metrics
were computed at K=5 and K=10. Hybrid used α=1, β=1, k=60. The model was loaded
once locally before the 82-question run.

| Mode | Recall@5 | Recall@10 | MRR |
| --- | ---: | ---: | ---: |
| Semantic only | 0.9329 | 0.9756 | 0.9817 |
| Keyword only | 0.1707 | 0.1829 | 0.2241 |
| Weighted hybrid | 0.9146 | 0.9756 | 0.9726 |

Weighted hybrid matched semantic Recall@10 but was slightly lower on Recall@5
and MRR. These equal-weight results do not show that hybrid improves over
semantic-only retrieval; tuning weights on this dev set remains future work.

## Real query latency

The following wall times are from the actual Supabase evaluation run. Semantic
latency includes local query embedding and its database search. Hybrid includes
both channels and Python fusion. p95 is nearest-rank over 82 query timings.

| Mode | Minimum | Median | p95 | Maximum |
| --- | ---: | ---: | ---: | ---: |
| Semantic | 107.115 ms | 120.784 ms | 215.236 ms | 244.517 ms |
| Keyword | 87.082 ms | 92.886 ms | 115.532 ms | 479.238 ms |
| Hybrid | 195.688 ms | 222.572 ms | 315.945 ms | 630.158 ms |

## Retrieved examples

### Natural-language smoke query

Query: “Which semi-professional football club was based in Adelaide, South
Australia?” The real hybrid CLI returned **Enfield City FC** at rank 1, with
both semantic and keyword rank 1. Its `doc_id` is
`9592c8d5d46c50920a669c2ed6363b12f923bc6f20c072161e69d807643bc224`, its
`chunk_id` is
`8b23113518999fc52bfc40e0547981748249f37b8c15787285ad09e4b4b87838`, and its
source provenance points to the pinned HotpotQA train record. The CLI reported
0.972 s retrieval time and 0.218 s model initialization for this one query.

### Evidence-qualified dev cases

- `5a8f9725554299458435d683`: the gold titles are ESPN College Football Friday
  Primetime and Dusty Dvoracek. Semantic and hybrid found one title in the top
  five and both by rank 10 (Recall@5=0.5, Recall@10=1.0, MRR=1.0). Keyword
  returned no results for this question.
- `5a73fe9b5542993a88ae2ee2`: the gold titles are Agave and Sisal. The first
  semantic/hybrid result was Sisal; only one of the two exact gold title aliases
  appeared by rank 10 (Recall@5=0.5, Recall@10=0.5, MRR=1.0). `Agave
  decipiens` did not count as the gold alias `Agave` under the explicit exact
  normalized-title metric.

## Limitations

- The current generated `tsv` indexes chunk text only; it does not include the
  source title. This can contribute to weak keyword recall for title/name
  queries. The schema was intentionally left unchanged in this milestone.
- The 82-question eligible subset is small and biased toward evidence present
  in the first 1,000 documents. The remaining 118 dev questions were excluded
  because their complete evidence is absent from this indexed subset.
- Hybrid uses equal weights and does not improve on semantic-only results in
  these aggregate measurements. No final-evaluation set was used for tuning.
- Retrieval metrics are source-title metrics; they do not validate exact
  sentence citation, claim entailment, answer correctness, contradictions, or
  abstention.
- No 10K/50K retrieval behavior, second chunking strategy, Gemini RAG, HTTP
  retrieval route, or UI was tested or implemented.

## Reproduction

Run from the project root with `.env` configured and the existing local BGE
cache available:

```powershell
.venv\Scripts\python.exe scripts\retrieve.py --mode semantic --query "Which semi-professional football club was based in Adelaide, South Australia?"
.venv\Scripts\python.exe scripts\retrieve.py --mode keyword --query "Which semi-professional football club was based in Adelaide, South Australia?"
.venv\Scripts\python.exe scripts\retrieve.py --mode hybrid --query "Which semi-professional football club was based in Adelaide, South Australia?" --semantic-weight 1 --keyword-weight 1 --rrf-k 60
.venv\Scripts\python.exe scripts\evaluate_retrieval.py --top-k 10 --candidate-k 20 --semantic-weight 1 --keyword-weight 1 --rrf-k 60
.venv\Scripts\python.exe -m pytest -q
```
