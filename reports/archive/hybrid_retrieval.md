# Phase 2 — Hybrid Retrieval

Date: 2026-10-24

Status: frozen Phase 2 baseline from the former Mindo-backed 1,000-document
subset. During Phase 1E, Mindo remained untouched; the same subset was loaded
into the dedicated Evidence_AI project with title-weighted FTS and halfvec.
Current measurements are in `reports/phase_1e_optimized.md`.

## Implementation

- Semantic retrieval embeds a natural-language query locally with
  `BAAI/bge-small-en-v1.5`, validates its 384 finite dimensions, then orders
  rows by pgvector cosine distance.
- Keyword retrieval uses the existing generated `tsv` column and GIN index,
  with `ts_rank_cd` ranking.
- The initial evaluation exposed an overly restrictive keyword query: ordinary
  adjacent terms passed to `websearch_to_tsquery` use AND semantics. Keyword
  retrieval now lets PostgreSQL tokenize the bound input with English
  `to_tsvector`, which stems terms and removes stopwords, then folds the unique
  normalized lexemes into an OR `tsquery` with PostgreSQL's `tsquery || tsquery`
  operator. User text is never concatenated into SQL or manually tokenized.
  Empty/whitespace queries return no hits without a database call; punctuation
  and stopword-only queries produce no query terms; duplicate terms collapse
  during `tsvector` normalization.
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

Before/after evaluation used the same 82 eligible questions, 1,000 indexed
documents, candidate K=20, output K=10, and equal-weight RRF α=1, β=1, k=60.
The before run used `websearch_to_tsquery`; the after run used the OR query.
Semantic retrieval was unchanged. The keyword query change raised keyword
recall, while the equal-weight hybrid regressed because the broader keyword
list contributed more off-target results to RRF.

| Mode | Before Recall@5 | After Recall@5 | Before Recall@10 | After Recall@10 | Before MRR | After MRR |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Semantic only | 0.9329 | 0.9329 | 0.9756 | 0.9756 | 0.9817 | 0.9817 |
| Keyword only | 0.1707 | 0.3598 | 0.1829 | 0.5732 | 0.2241 | 0.3232 |
| Weighted hybrid | 0.9146 | 0.7378 | 0.9756 | 0.9268 | 0.9726 | 0.7418 |

## Real query latency

The following medians are from the matching before and after Supabase runs.
Semantic latency includes local query embedding and its database search.
Hybrid includes both channels and Python fusion. Each run loaded the model once
and measured 82 questions. The remote database showed long-tail timing outliers;
these two runs do not isolate network/service variance from query-cost changes.

| Mode | Before median | After median | After p95 | After maximum |
| --- | ---: | ---: | ---: | ---: |
| Semantic | 131.504 ms | 149.018 ms | 564.692 ms | 1,732.402 ms |
| Keyword | 105.984 ms | 131.429 ms | 291.315 ms | 1,498.065 ms |
| Hybrid | 236.530 ms | 286.058 ms | 978.182 ms | 1,844.709 ms |

## Retrieved examples

### Evidence-qualified dev cases

- Improved keyword case `5a8dc02d554299441c6ba083`: “What element of Christina
  Aguilera's ‘Red Hot Kinda Love’ makes it a hip hop track?” Before the OR fix,
  keyword retrieval returned no hits. Afterward, it returned `Hip hop music`
  first and the title-level metrics rose from 0.0 to 1.0 at Recall@5, Recall@10,
  and MRR.
- Regressed keyword case `5a76446b5542994ccc918748`: “Where is the high school
  that Gorecki graduated from?” The old AND query returned `Reid Gorecki` at
  rank 1. The OR query promoted generic high-school pages; no gold title was in
  its top 10, so all three keyword metrics fell from 0.5/0.5/1.0 to zero.
- Hybrid improved for `5a8f9725554299458435d683` (the ESPN College Football
  Friday Primetime question): Recall@5 rose from 0.5 to 1.0; Recall@10 and MRR
  remained 1.0.
- Hybrid regressed for the Gorecki question: Recall@5 fell from 1.0 to 0.0,
  Recall@10 from 1.0 to 1.0, and MRR from 1.0 to 0.1667 (the first matching
  title moved to rank 6).

## Limitations

- The current generated `tsv` indexes chunk text only; it does not include the
  source title. This can contribute to weak keyword recall for title/name
  queries. The schema was intentionally left unchanged in this milestone.
- The 82-question eligible subset is small and biased toward evidence present
  in the first 1,000 documents. The remaining 118 dev questions were excluded
  because their complete evidence is absent from this indexed subset.
- OR improved keyword recall on this dev subset but increased noise. Equal-
  weight hybrid lost against the before run and semantic-only retrieval. Weight
  tuning or a better lexical ranker requires a separate dev-only experiment;
  no final-evaluation set was used for tuning.
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
.venv\Scripts\python.exe scripts\evaluate_retrieval.py --top-k 10 --candidate-k 20 --semantic-weight 1 --keyword-weight 1 --rrf-k 60 --details-json "$env:TEMP\evidenceai_keyword_details.json"
.venv\Scripts\python.exe -m pytest -q
```
